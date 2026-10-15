import os
import time
import requests
from typing import Optional


class GitHubDeepSource:
    GITHUB_API = "https://api.github.com"
    RATE_LIMIT_SLEEP = 0.5

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
        self.rate_limited = False

    def search(self, query: str, max_results: int = 10) -> dict:
        """
        Search GitHub repos matching query, then fetch issues + README from top-3.
        Returns combined results with source_type populated.
        """
        results = []
        self.rate_limited = False
        self._errors: list[str] = []

        # Step 1: Search repos
        repo_params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": 3,
        }

        try:
            time.sleep(self.RATE_LIMIT_SLEEP)
            resp = requests.get(
                f"{self.GITHUB_API}/search/repositories",
                params=repo_params,
                headers=self.headers,
                timeout=10,
            )

            if resp.status_code == 429:
                self.rate_limited = True
                return {"results": results, "rate_limited": True}

            resp.raise_for_status()
            repos = resp.json().get("items", [])
        except Exception as e:
            return {"results": [], "error": str(e), "rate_limited": False}

        # Step 2: For each repo, fetch issues + README. GitHub's wiki lives in
        # a separate repository, not at /repos/{owner}/{repo}/contents/wiki.
        # That endpoint usually returns 404 and cost three serial requests.
        for repo in repos[:3]:
            owner = repo["owner"]["login"]
            repo_name = repo["name"]

            # Fetch issues
            issue_results = self._fetch_issues(owner, repo_name)
            results.extend(issue_results)
            if self.rate_limited:
                break

            # Add README if it exists
            time.sleep(self.RATE_LIMIT_SLEEP)
            try:
                readme_resp = requests.get(
                    f"{self.GITHUB_API}/repos/{owner}/{repo_name}/readme",
                    headers=self.headers,
                    timeout=10,
                )
                if readme_resp.status_code == 200:
                    readme_data = readme_resp.json()
                    results.append({
                        "title": f"README: {repo_name}",
                        "url": f"https://github.com/{owner}/{repo_name}#readme",
                        "snippet": readme_data.get("download_url", ""),
                        "source_type": "readme",
                    })
                elif readme_resp.status_code == 429:
                    self.rate_limited = True
                    break
                elif readme_resp.status_code != 404:
                    self._errors.append(
                        f"README request for {owner}/{repo_name} returned HTTP "
                        f"{readme_resp.status_code}"
                    )
            except Exception as e:
                self._errors.append(f"README request for {owner}/{repo_name}: {e}")

        response = {
            "results": results[:max_results],
            "rate_limited": self.rate_limited,
        }
        if self._errors:
            response["error"] = "; ".join(self._errors)
        return response

    def search_issues(self, query: str, max_results: int = 10) -> dict:
        """
        Search GitHub issues directly via /search/issues.
        More targeted when you know what you're looking for.
        """
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": max_results,
        }

        try:
            time.sleep(self.RATE_LIMIT_SLEEP)
            resp = requests.get(
                f"{self.GITHUB_API}/search/issues",
                params=params,
                headers=self.headers,
                timeout=10,
            )

            if resp.status_code == 429:
                self.rate_limited = True
                return {"results": [], "rate_limited": True}

            resp.raise_for_status()
            issues = resp.json().get("items", [])
        except Exception as e:
            return {"results": [], "error": str(e), "rate_limited": False}

        results = []
        for issue in issues:
            results.append({
                "title": issue.get("title", ""),
                "url": issue.get("html_url", ""),
                "snippet": issue.get("body", "")[:200],
                "source_type": "issue",
            })

        return {
            "results": results,
            "rate_limited": self.rate_limited,
        }

    def _fetch_issues(self, owner: str, repo: str) -> list:
        """Fetch top issues from a repo."""
        results = []
        params = {
            "state": "all",
            "per_page": 5,
            "sort": "updated",
        }

        try:
            time.sleep(self.RATE_LIMIT_SLEEP)
            resp = requests.get(
                f"{self.GITHUB_API}/repos/{owner}/{repo}/issues",
                params=params,
                headers=self.headers,
                timeout=10,
            )

            if resp.status_code == 429:
                self.rate_limited = True
                return results

            if resp.status_code != 200:
                self._errors.append(
                    f"Issue request for {owner}/{repo} returned HTTP {resp.status_code}"
                )
                return results

            issues = resp.json()
            for issue in issues:
                results.append({
                    "title": issue.get("title", ""),
                    "url": issue.get("html_url", ""),
                    "snippet": issue.get("body", "")[:200] if issue.get("body") else "",
                    "source_type": "issue",
                })
        except Exception as e:
            self._errors.append(f"Issue request for {owner}/{repo}: {e}")

        return results

    def _fetch_wiki(self, owner: str, repo: str) -> list:
        """Fetch wiki pages from a repo (if enabled)."""
        results = []

        try:
            time.sleep(self.RATE_LIMIT_SLEEP)
            resp = requests.get(
                f"{self.GITHUB_API}/repos/{owner}/{repo}/contents/wiki",
                headers=self.headers,
                timeout=10,
            )

            if resp.status_code == 429:
                self.rate_limited = True
                return results

            if resp.status_code != 200:
                return results

            wiki_files = resp.json()
            if isinstance(wiki_files, list):
                for file in wiki_files[:3]:
                    wiki_name = file.get('name', '')
                    results.append({
                        "title": f"Wiki: {wiki_name}",
                        "url": f"https://github.com/{owner}/{repo}/wiki/{wiki_name}",
                        "snippet": wiki_name,
                        "source_type": "wiki",
                    })
        except Exception:  # wiki may be disabled or empty; not fatal
            pass

        return results

    def fetch(self, url: str) -> Optional[str]:
        """Fetch content from a github.com URL (issue, wiki page, or PR)."""
        if not url.startswith("https://github.com/"):
            return None

        try:
            time.sleep(self.RATE_LIMIT_SLEEP)
            resp = requests.get(url, headers=self.headers, timeout=10)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            return f"Error fetching {url}: {str(e)}"
