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

# Shared dictionary to store URL validity
dict_urls = {}
# Lock to manage access to dict_urls
dict_lock = threading.Lock()
count_lock = threading.Lock()

completed_count = 0

# File to save progress
progress_file = 'progress.json'
backup_file = 'backup.json'
backup_file2 = 'backup2.json'

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
    with dict_lock:
        with open(progress_file, 'wb') as file:  # Use binary mode for faster writing
            file.write(orjson.dumps(dict_urls, option=orjson.OPT_INDENT_2))

def save_backup_progress():
    with open(backup_file, 'wb') as file:
        file.write(orjson.dumps(dict_urls, option=orjson.OPT_INDENT_2))
    # print(f"Backup progress saved to {backup_file}")

def save_backup_progress2():
    with open(backup_file2, 'wb') as file:
        file.write(orjson.dumps(dict_urls, option=orjson.OPT_INDENT_2))
    print(f"Backup progress saved to {backup_file2}")


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
            # print(f"\t{completed_count} -> completed | URL already checked: {url}, {doc_index}")
            return dict_urls[url]
    
    with count_lock:
        completed_count += 1

    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            return process_valid_response(response, url, doc_index)
        else:
            # print(f"Non-200 response for {url}, checking Wayback Machine...")
            archived_url = check_wayback_machine(url)
            if archived_url:
                # print(f"Found archived URL: {archived_url}")
                response = session.get(archived_url, timeout=10)
                if response.status_code == 200:
                    return process_valid_response(response, url, doc_index, archived=True)
                
            else:
                # print(f"Could not find archived URL for {url}")
                pass
    except requests.RequestException:
        # print(f"Request exception for {url}")
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
            if not archived:
                dict_urls[url] = True
            else:
                dict_urls[url] = "archived"    

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

def process_urls_from_csv(doc_df, limit):
    total_urls = len(doc_df)
    global completed_count 
    completed_count = len(dict_urls)
    remaining_to_process = limit


    report_interval = 100
    backup_interval = 1000
    local_count = 0
    max_workers = 16 * 4
    start_time = time.time()

    try:

        # remaining_df = doc_df.iloc[completed_count:]

        new_urls = [(row["Url"], row["DocIndex"]) for _, row in reversed(list(doc_df.iterrows())) if row["Url"] not in dict_urls]

        new_urls = new_urls[:limit]  # Limit processing to the user-specified number
    except KeyError:
        save_backup_progress2()
        print("Error reading URL and DocIndex from CSV. Exiting...")
        sys.exit(1)

    if not new_urls:
        save_backup_progress2()
        print("No new URLs to process. Exiting...")
        sys.exit(0)

    print(f"Processing {len(new_urls)} new URLs...")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_url_validity, url, doc_index): (url, doc_index) for url, doc_index in new_urls}

            for future in concurrent.futures.as_completed(futures):
                local_count += 1
                try:
                    future.result()
                except Exception as e:
                    # PRINT THE url and doc_index
                    url, doc_index = futures[future]
                    
                    print(f"Exception occurred: {e}")

                if local_count % report_interval == 0:
                    print(f"Progress: {completed_count}/{total_urls} URLs processed by {time.ctime()} will complete in {((time.time() - start_time) / completed_count) * (total_urls - completed_count) / 60:.2f} minutes")
                save_progress()
                if local_count % backup_interval == 0:
                    print("Local_count: ", local_count, " | completed_count: ", completed_count), " backing up progress..."
                    save_backup_progress()
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Saving progress and exiting gracefully...")
        save_progress()
        sys.exit(0)
    save_progress()
    save_backup_progress()
    # save_backup_progress2()
    print("Processing complete. Final progress & Backup saved.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <number_of_new_urls_to_process>")
        sys.exit(1)
    try:
        limit = int(sys.argv[1])
    except ValueError:
        print("Please enter a valid integer for the number of new URLs to process.")
        sys.exit(1)
    
    doc_df = pd.read_csv('doc.csv', delimiter='\t', usecols=['Url', 'DocIndex'])
    process_urls_from_csv(doc_df, limit)
