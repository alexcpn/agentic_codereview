import requests
import re
from collections import defaultdict
import logging as log


def get_pr_diff_url(repo_url, pr_number):
    """ 
    Get the diff URL for a specific pull request number.
    Args:
        repo_url (str): The URL of the GitHub repository.
        pr_number (int): The pull request number.
    """
    pr_diff_url = f"https://patch-diff.githubusercontent.com/raw/{repo_url.split('/')[-2]}/{repo_url.split('/')[-1]}/pull/{pr_number}.diff"
    response = requests.get(pr_diff_url,verify=False)

    if response.status_code != 200:
        log.error(f"Failed to fetch diff: {response.status_code}")
        raise ValueError(f"Failed to fetch diff: {response.status_code}")

    diff_text = response.text
    file_diffs = defaultdict(str)
    file_diff_pattern = re.compile(r'^diff --git a/(.*?) b/\1$', re.MULTILINE)
    split_points = list(file_diff_pattern.finditer(diff_text))
    for i, match in enumerate(split_points):
        file_path = match.group(1)
        start = match.start()
        end = split_points[i + 1].start() if i + 1 < len(split_points) else len(diff_text)
        file_diffs[file_path] = diff_text[start:end]
    return file_diffs

