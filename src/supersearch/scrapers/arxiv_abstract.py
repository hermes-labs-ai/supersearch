"""
arXiv abstract scraper.

Given an arXiv ID or URL, fetch the paper's abstract-page metadata: title,
authors, abstract, categories, submission date, DOI, and PDF URL. Uses the
arXiv Atom API — no scraping of HTML, no auth, rate-limit friendly.

Usage:
    python3 -m supersearch.scrapers.arxiv_abstract 2501.12345
    python3 -m supersearch.scrapers.arxiv_abstract https://arxiv.org/abs/2501.12345
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from typing import Optional

import requests


API_URL = "https://export.arxiv.org/api/query"
NS_ATOM = "{http://www.w3.org/2005/Atom}"
NS_ARXIV = "{http://arxiv.org/schemas/atom}"
ID_REGEX = re.compile(r"(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(v\d+)?")


def _normalize_id(raw: str) -> Optional[str]:
    """Return a bare arXiv id like '2501.12345' from id, URL, or PDF URL."""
    s = raw.strip()
    m = ID_REGEX.search(s)
    return m.group(0) if m else None


def fetch(id_or_url: str, timeout: int = 15) -> dict:
    """Fetch arXiv abstract metadata. Returns {} and sets 'error' on failure."""
    arxiv_id = _normalize_id(id_or_url)
    if not arxiv_id:
        return {"error": f"could not parse arXiv id from: {id_or_url}"}

    try:
        resp = requests.get(
            API_URL,
            params={"id_list": arxiv_id.split("v")[0], "max_results": 1},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"id": arxiv_id, "error": f"request failed: {e}"}

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        return {"id": arxiv_id, "error": f"parse failed: {e}"}

    entry = root.find(f"{NS_ATOM}entry")
    if entry is None:
        return {"id": arxiv_id, "error": "no entry in response"}

    def _text(tag: str) -> str:
        el = entry.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    title = " ".join(_text(f"{NS_ATOM}title").split())
    summary = " ".join(_text(f"{NS_ATOM}summary").split())
    published = _text(f"{NS_ATOM}published")
    updated = _text(f"{NS_ATOM}updated")

    authors = []
    for a in entry.findall(f"{NS_ATOM}author"):
        name_el = a.find(f"{NS_ATOM}name")
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    categories = []
    primary_cat = entry.find(f"{NS_ARXIV}primary_category")
    if primary_cat is not None and primary_cat.get("term"):
        categories.append(primary_cat.get("term"))
    for cat in entry.findall(f"{NS_ATOM}category"):
        term = cat.get("term")
        if term and term not in categories:
            categories.append(term)

    doi_el = entry.find(f"{NS_ARXIV}doi")
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None

    abs_url = None
    pdf_url = None
    for link in entry.findall(f"{NS_ATOM}link"):
        href = link.get("href", "")
        if link.get("title") == "pdf" or href.endswith(".pdf"):
            pdf_url = href
        elif link.get("rel") == "alternate" and "abs" in href:
            abs_url = href

    return {
        "id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": summary,
        "published": published,
        "updated": updated,
        "categories": categories,
        "doi": doi,
        "abs_url": abs_url or f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
    }


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.arxiv_abstract <id_or_url>")
        return 1
    result = fetch(argv[1])
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
