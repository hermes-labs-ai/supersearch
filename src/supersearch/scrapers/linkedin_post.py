"""LinkedIn post text cleaner. Takes raw SuperSearch HTML output and extracts clean post text."""

import json
import re
import sys
from pathlib import Path


def clean_linkedin_text(raw_text):
    """Clean LinkedIn post text from SuperSearch raw HTML dump.

    SuperSearch --raw captures LinkedIn post text but includes nav, sign-in prompts,
    and boilerplate. This extracts just the post content.
    """
    # Remove common LinkedIn boilerplate
    noise_patterns = [
        r"Sign in.*?Sign in",
        r"Join now.*?Join now",
        r"Skip to main content",
        r"LinkedIn and 3rd parties.*?Learn more",
        r"Agree & Join LinkedIn",
        r"By clicking Continue.*?Privacy Policy",
        r"Already on LinkedIn\? Sign in",
        r"New to LinkedIn\? Join now",
        r"Don't miss out.*",
        r"Like\s+Comment\s+Share",
        r"\d+ likes?\s*·\s*\d+ comments?",
        r"Report this post",
        r"See more$",
    ]

    text = raw_text
    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.I | re.DOTALL)

    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    # Remove very short lines (likely nav elements)
    lines = [line.strip() for line in text.split("\n") if len(line.strip()) > 20]

    return "\n".join(lines).strip()


def process_directory(raw_dir):
    """Process all .txt files in a SuperSearch --raw output directory."""
    output = {"posts": [], "total_chars": 0}

    raw_path = Path(raw_dir)
    if not raw_path.exists():
        return output

    for txt_file in raw_path.glob("*.txt"):
        with open(txt_file) as f:
            content = f.read()

        # Extract URL and title
        lines = content.split("\n", 3)
        url = lines[0].replace("URL: ", "") if lines[0].startswith("URL:") else ""
        title = lines[1].replace("TITLE: ", "") if len(lines) > 1 and lines[1].startswith("TITLE:") else ""

        # Only process LinkedIn URLs
        if "linkedin.com" not in url:
            continue

        body = lines[2] if len(lines) > 2 else ""
        cleaned = clean_linkedin_text(body)

        if len(cleaned) > 50:
            output["posts"].append({
                "url": url,
                "title": title,
                "text": cleaned,
                "chars": len(cleaned),
            })
            output["total_chars"] += len(cleaned)

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.linkedin_post <raw_dir>")
        print("  Process SuperSearch --raw output directory for LinkedIn posts")
        sys.exit(1)
    result = process_directory(sys.argv[1])
    print(json.dumps(result, indent=2))
