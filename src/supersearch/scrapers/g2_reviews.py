"""G2 review scraper. Extracts negative reviews mentioning bugs, failures, reliability."""

import json
import re
import sys
import requests
from bs4 import BeautifulSoup

PAIN_KEYWORDS = [
    "bug", "error", "broken", "unreliable", "wrong", "inaccurate",
    "crash", "fail", "slow", "confusing", "frustrat", "disappoint",
    "missing", "doesn't work", "does not work", "poor", "terrible",
    "horrible", "waste", "regret", "worst", "unusable",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}


def scrape_reviews(product_name):
    """Scrape G2 reviews for pain signals."""
    output = {
        "product": product_name,
        "reviews_found": 0,
        "negative_reviews": [],
        "pain_keywords_found": [],
        "source_url": None,
    }

    slug = product_name.lower().replace(" ", "-").replace(".", "")
    url = f"https://www.g2.com/products/{slug}/reviews"
    output["source_url"] = url

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            # Try alternative slug patterns
            for alt_slug in [slug.replace("-", ""), slug + "-ai", slug + "-platform"]:
                alt_url = f"https://www.g2.com/products/{alt_slug}/reviews"
                resp = requests.get(alt_url, headers=HEADERS, timeout=15)
                if resp.status_code == 200:
                    output["source_url"] = alt_url
                    break

        if resp.status_code != 200:
            return output

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(separator=" ").lower()

        # Find pain keywords
        for kw in PAIN_KEYWORDS:
            if kw in text and kw not in output["pain_keywords_found"]:
                output["pain_keywords_found"].append(kw)

        # Extract review snippets containing pain keywords
        for element in soup.find_all(["p", "div", "span"], string=re.compile("|".join(PAIN_KEYWORDS[:10]), re.I)):
            review_text = element.get_text(strip=True)
            if 20 < len(review_text) < 500:
                output["negative_reviews"].append(review_text)
                if len(output["negative_reviews"]) >= 10:
                    break

        output["reviews_found"] = len(output["negative_reviews"])

    except Exception:  # noqa: silent — G2 is flaky; return whatever we got
        pass

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.g2_reviews <product_name>")
        sys.exit(1)
    result = scrape_reviews(sys.argv[1])
    print(json.dumps(result, indent=2))
