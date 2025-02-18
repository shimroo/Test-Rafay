#!/bin/bash

# Number of times to run the command
num_iterations=500  # Change as needed
number_of_pages=250
wait_time=5

for ((i=1; i<=num_iterations; i++))
do
    echo "Running iteration $i... running pages.py with $number_of_pages pages"
    python3 pages.py "$number_of_pages"
    
    echo -e "\tIteration $i complete. Waiting for $wait_time seconds..."
    sleep $wait_time

    # After every 10 iterations, commit and push to Git
    if ((i % 10 == 0)); then
        echo "Iteration $i: Committing and pushing to Git..."

        # Add all changes to staging
        git add .

        # Commit the changes
        git commit -m "Iteration $i : Automatic commit"

        # Push the changes to the remote repository
        git push 

        echo -e "\tCommit and push complete. Continuing the loop..."
    fi

    sleep $wait_time2

done
