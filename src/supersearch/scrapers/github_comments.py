"""GitHub user comment scraper. Pulls issue/PR comments for psychographic profiling.

Issue and PR comments are psychographic gold: reasoning under peer scrutiny,
technical argument style, how someone handles disagreement.
"""

import json
import subprocess
import sys
import time


def get_token():
    """Get GitHub token from gh CLI for 5,000 req/hr (vs 60 unauthenticated)."""
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def api_get(path, token=None):
    """GitHub API GET request."""
    headers = ["-H", "Accept: application/vnd.github+json"]
    if token:
        headers += ["-H", f"Authorization: Bearer {token}"]
    try:
        result = subprocess.run(
            ["curl", "-s"] + headers + [f"https://api.github.com{path}"],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(result.stdout) if result.stdout else None

        # Check rate limit
        if isinstance(data, dict) and data.get("message", "").startswith("API rate limit"):
            return {"error": "rate_limited", "message": data["message"]}

        return data
    except Exception:
        return None


def get_user_comments(username, max_comments=50):
    """Get a user's issue and PR comments across all repos.

    Returns comments sorted by most recent, with repo context.
    """
    token = get_token()
    output = {
        "username": username,
        "comments": [],
        "total_chars": 0,
        "repos_active_in": [],
        "error": None,
    }

    # Search for issues/PRs where this user commented
    # GitHub search API: comments by user
    search_url = f"/search/issues?q=commenter:{username}+type:issue&sort=updated&per_page=20"
    issues = api_get(search_url, token)

    if not issues or isinstance(issues, dict) and "items" not in issues:
        if isinstance(issues, dict) and issues.get("error") == "rate_limited":
            output["error"] = "GitHub API rate limited. Use gh auth login for 5000 req/hr."
        return output

    time.sleep(1)  # Rate limit respect

    # For each issue, get the user's comments
    for item in issues.get("items", [])[:15]:
        repo_full = item.get("repository_url", "").replace("https://api.github.com/repos/", "")
        issue_num = item.get("number")
        if not repo_full or not issue_num:
            continue

        if repo_full not in output["repos_active_in"]:
            output["repos_active_in"].append(repo_full)

        # Get comments on this issue
        time.sleep(0.5)
        comments = api_get(f"/repos/{repo_full}/issues/{issue_num}/comments?per_page=30", token)
        if not comments or not isinstance(comments, list):
            continue

        for comment in comments:
            if comment.get("user", {}).get("login", "").lower() == username.lower():
                body = comment.get("body", "")
                if len(body) > 20:
                    output["comments"].append({
                        "repo": repo_full,
                        "issue": issue_num,
                        "body": body[:2000],  # Cap per comment
                        "created_at": comment.get("created_at", ""),
                        "url": comment.get("html_url", ""),
                    })
                    output["total_chars"] += len(body[:2000])

                    if len(output["comments"]) >= max_comments:
                        return output

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.github_comments <username> [max_comments]")
        sys.exit(1)
    max_c = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    result = get_user_comments(sys.argv[1], max_comments=max_c)
    print(json.dumps(result, indent=2))
