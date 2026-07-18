"""GitHub org tech stack detection. Confirms which AI frameworks a company uses."""

import json
import subprocess
import sys
import time


# AI frameworks to detect in dependencies
AI_FRAMEWORKS = [
    "langchain", "langgraph", "crewai", "autogen", "anthropic", "openai",
    "litellm", "dspy", "smolagents", "agno", "llama-index", "llama_index",
    "pydantic-ai", "instructor", "semantic-kernel", "haystack", "guardrails-ai",
    "nemoguardrails", "promptfoo", "transformers", "torch", "tensorflow",
    "ollama", "vllm", "huggingface-hub",
]


def get_token():
    """Get GitHub token from gh CLI."""
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def api_get(path, token=None):
    """GitHub API GET request via curl."""
    headers = ["-H", "Accept: application/vnd.github+json"]
    if token:
        headers += ["-H", f"Authorization: Bearer {token}"]
    try:
        result = subprocess.run(
            ["curl", "-s"] + headers + [f"https://api.github.com{path}"],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(result.stdout) if result.stdout else None
    except Exception:
        return None


def scan_org(org_name):
    """Scan a GitHub org for AI framework usage."""
    token = get_token()
    output = {"org": org_name, "repos": [], "frameworks_detected": [], "languages": {}}

    # Get org repos (up to 100)
    repos = api_get(f"/orgs/{org_name}/repos?per_page=100&sort=updated", token)
    if not repos or isinstance(repos, dict):
        # Try as user
        repos = api_get(f"/users/{org_name}/repos?per_page=100&sort=updated", token)
    if not repos or isinstance(repos, dict):
        return output

    for repo in repos[:30]:  # Limit to 30 most recent
        name = repo.get("name", "")
        lang = repo.get("language", "")
        stars = repo.get("stargazers_count", 0)

        if lang:
            output["languages"][lang] = output["languages"].get(lang, 0) + 1

        repo_info = {"name": name, "language": lang, "stars": stars, "frameworks": []}

        # Check dependency files
        time.sleep(0.5)  # Rate limit respect
        for dep_file in ["requirements.txt", "pyproject.toml", "package.json", "Pipfile"]:
            content = api_get(f"/repos/{org_name}/{name}/contents/{dep_file}", token)
            if content and isinstance(content, dict) and "download_url" in content:
                try:
                    dl = subprocess.run(
                        ["curl", "-s", content["download_url"]],
                        capture_output=True, text=True, timeout=10,
                    )
                    text = dl.stdout.lower()
                    for fw in AI_FRAMEWORKS:
                        if fw.lower() in text and fw not in repo_info["frameworks"]:
                            repo_info["frameworks"].append(fw)
                except Exception:  # noqa: silent — best-effort framework detection per file
                    pass

        if repo_info["frameworks"]:
            output["repos"].append(repo_info)
            for fw in repo_info["frameworks"]:
                if fw not in output["frameworks_detected"]:
                    output["frameworks_detected"].append(fw)

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.github_org <org_name>")
        sys.exit(1)
    result = scan_org(sys.argv[1])
    print(json.dumps(result, indent=2))
