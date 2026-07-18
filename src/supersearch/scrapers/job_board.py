"""Job board scraper. Detects AI framework usage + buying signals from careers pages."""

import json
import re
import sys
import requests
from bs4 import BeautifulSoup

BUYING_SIGNALS = [
    "ai reliability", "ai safety", "ai governance", "ai compliance",
    "ai audit", "ai risk", "ai ethics", "responsible ai", "ai trust",
    "model evaluation", "model testing", "model monitoring",
    "eu ai act", "iso 42001", "ai policy",
]

FRAMEWORK_KEYWORDS = [
    "langchain", "langgraph", "crewai", "autogen", "anthropic", "openai",
    "litellm", "dspy", "smolagents", "llama-index", "llamaindex",
    "semantic-kernel", "pydantic-ai", "instructor", "haystack",
    "huggingface", "transformers", "pytorch", "tensorflow", "ollama", "vllm",
]

CAREERS_PATTERNS = [
    "https://boards.greenhouse.io/{slug}",
    "https://jobs.lever.co/{slug}",
    "https://jobs.ashbyhq.com/{slug}",
    "https://{slug}.breezy.hr",
    "https://apply.workable.com/{slug}",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def scrape_careers(company_slug):
    """Try common careers page patterns and scrape job listings."""
    output = {
        "company": company_slug,
        "jobs_found": 0,
        "framework_mentions": [],
        "buying_signals": [],
        "source_url": None,
        "jobs": [],
    }

    for pattern in CAREERS_PATTERNS:
        url = pattern.format(slug=company_slug.lower().replace(" ", ""))
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.text) > 500:
                output["source_url"] = url
                soup = BeautifulSoup(resp.text, "lxml")
                text = soup.get_text(separator=" ").lower()

                # Find framework mentions
                for fw in FRAMEWORK_KEYWORDS:
                    if fw in text and fw not in output["framework_mentions"]:
                        output["framework_mentions"].append(fw)

                # Find buying signals
                for signal in BUYING_SIGNALS:
                    if signal in text and signal not in output["buying_signals"]:
                        output["buying_signals"].append(signal)

                # Extract job titles
                for tag in soup.find_all(["a", "h2", "h3", "div"], class_=re.compile(r"job|opening|position|title", re.I)):
                    title = tag.get_text(strip=True)
                    if 5 < len(title) < 120:
                        output["jobs"].append(title)

                output["jobs_found"] = len(output["jobs"])
                break
        except Exception:
            continue

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.job_board <company_slug>")
        sys.exit(1)
    result = scrape_careers(sys.argv[1])
    print(json.dumps(result, indent=2))
