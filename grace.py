import requests
from bs4 import BeautifulSoup
import pandas as pd
import concurrent.futures
import threading
import json
import orjson
import os
import sys
import time
import signal

# Shared dictionary to store URL validity
dict_urls = {}
# Lock to manage access to dict_urls
dict_lock = threading.Lock()
count_lock = threading.Lock()

completed_count = 0

# File to save progress
progress_file = 'progress.json'
backup_file = 'backup.json'

# Directories for saving files
html_dir = "downloaded_html"
txt_dir = "downloaded_txt"

# Create directories if they do not exist
os.makedirs(html_dir, exist_ok=True)
os.makedirs(txt_dir, exist_ok=True)

session = requests.Session()
session.headers.update({
    'User-Agent': 'MyScript/1.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
})

# Load existing progress from file if it exists
if os.path.exists(progress_file):
    with open(progress_file, 'r') as file:
        dict_urls = json.load(file)

def save_progress():
    """Save the progress to a file."""
    with dict_lock:
        with open(progress_file, 'wb') as file:  # Use binary mode for faster writing
            file.write(orjson.dumps(dict_urls, option=orjson.OPT_INDENT_2))

def save_backup_progress():
    """Save a backup of the progress."""
    with open(backup_file, 'wb') as file:
        file.write(orjson.dumps(dict_urls, option=orjson.OPT_INDENT_2))
    print(f"Backup progress saved to {backup_file}")

def graceful_exit(signum, frame):
    """Handles termination signals (SIGINT, SIGTERM), saves progress, and exits."""
    print("\nGraceful shutdown initiated... Saving progress.")
    save_progress()
    save_backup_progress()
    print("Progress saved. Exiting.")
    sys.exit(0)

# Register signal handlers for graceful termination
signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)

def check_wayback_machine(url):
    wayback_url = f"http://archive.org/wayback/available?url={url}"
    try:
        response = session.get(wayback_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'archived_snapshots' in data and 'closest' in data['archived_snapshots']:
                return data['archived_snapshots']['closest']['url']
    except requests.RequestException:
        pass
    return None

def check_url_validity(url, doc_index):
    global completed_count

    with dict_lock:
        if url in dict_urls:
            print(f"\t{completed_count} -> completed | URL already checked: {url}")
            return dict_urls[url]
    
    with count_lock:
        completed_count += 1

    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            return process_valid_response(response, url, doc_index)
        else:
            archived_url = check_wayback_machine(url)
            if archived_url:
                response = session.get(archived_url, timeout=10)
                if response.status_code == 200:
                    return process_valid_response(response, url, doc_index, archived=True)
                
    except requests.RequestException:
        pass
    
    with dict_lock:
        dict_urls[url] = False
    return False

def process_valid_response(response, url, doc_index, archived=False):
    content_length = int(response.headers.get('Content-Length', 0))
    if content_length > 5 * 1024:
        soup = BeautifulSoup(response.text, 'html.parser')
        content = soup.get_text().lower()
        invalid_keywords = ["page not available", "no longer available", "404", "500", "403", "site unavailable", "domain expired"]
        if any(keyword in content for keyword in invalid_keywords) and (not content.strip()):
            with dict_lock:
                dict_urls[url] = False
            return False
        with dict_lock:
            save_backup_progress()
            dict_urls[url] = "archived" if archived else True

        file_prefix = "archived_" if archived else ""
        html_filename = os.path.join(html_dir, f"{file_prefix}{doc_index}.html")
        txt_filename = os.path.join(txt_dir, f"{file_prefix}{doc_index}.txt")

        with open(html_filename, "w", encoding="utf-8") as html_file:
            html_file.write(response.text)
        with open(txt_filename, "w", encoding="utf-8") as text_file:
            text_file.write(content)
        return True
    
    with dict_lock:
        dict_urls[url] = False
    return False

def process_urls_from_csv(doc_df):
    total_urls = len(doc_df)
    global completed_count 
    completed_count = len(dict_urls)

    report_interval = 100
    backup_interval = 1000
    local_count = 0
    max_workers = 16 * 4
    start_time = time.time()
    script_start_time = time.time()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_url_validity, row["Url"], row["DocIndex"]): row["Url"] for _, row in doc_df.iterrows()}
            for future in concurrent.futures.as_completed(futures):
                local_count += 1
                try:
                    future.result()
                except Exception as e:
                    print(f"Exception occurred: {e}")

                if local_count % report_interval == 0:
                    elapsed_time = (time.time() - script_start_time) / 60
                    remaining_time = 30 - elapsed_time
                    print(f"Progress: {completed_count}/{total_urls} URLs processed. Time left: {remaining_time:.2f} minutes.")

                save_progress()
                if local_count % backup_interval == 0:
                    print("Local_count:", local_count, "| completed_count:", completed_count, "backing up progress...")
                    save_backup_progress()

                # Check if 30 minutes have passed
                if time.time() - script_start_time > 2 * 60:
                    print("\nTime limit reached (30 minutes). Saving progress and restarting...")
                    save_progress()
                    save_backup_progress()
                    print("Waiting 15 seconds before restarting...")
                    time.sleep(15)
                    os.execv(sys.executable, ['python'] + sys.argv)  # Restart script

    except KeyboardInterrupt:
        graceful_exit(None, None)

    save_progress()
    print("Processing complete. Final progress saved.")

if __name__ == "__main__":
    while True:
        print("Loading document data...")
        doc_df = pd.read_csv('test_doc.csv', delimiter='\t', usecols=['Url', 'DocIndex'])
        process_urls_from_csv(doc_df)
