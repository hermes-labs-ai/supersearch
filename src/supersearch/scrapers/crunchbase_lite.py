"""Lightweight funding data scraper from public pages (Tracxn, news articles)."""

import json
import re
import sys
import subprocess


def fetch_funding(company_name):
    """Get funding data by searching via SuperSearch --raw, then parsing."""
    output = {
        "company": company_name,
        "funding_rounds": [],
        "total_raised": None,
        "valuation": None,
        "investors": [],
        "founded": None,
        "employees": None,
    }

    # Use SuperSearch to find funding info. Run with the SAME interpreter that
    # imported this module (so the ``supersearch`` package resolves in whatever
    # environment we are installed in) and inherit the caller's cwd — no
    # hardcoded checkout path.
    query = f"{company_name} funding series raised valuation investors"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "supersearch", query],
            capture_output=True, text=True, timeout=30,
        )
        text = result.stdout.lower()
    except Exception:
        return output

    # Parse funding amounts
    money_pattern = re.compile(r'\$(\d+(?:\.\d+)?)\s*(million|billion|m|b)', re.I)
    for match in money_pattern.finditer(text):
        amount = float(match.group(1))
        unit = match.group(2).lower()
        if unit in ("billion", "b"):
            amount *= 1000
        output["funding_rounds"].append(f"${amount}M")

    # Parse valuation
    val_pattern = re.compile(r'valuation[^$]*\$(\d+(?:\.\d+)?)\s*(million|billion|m|b)', re.I)
    val_match = val_pattern.search(text)
    if val_match:
        val = float(val_match.group(1))
        unit = val_match.group(2).lower()
        if unit in ("billion", "b"):
            output["valuation"] = f"${val}B"
        else:
            output["valuation"] = f"${val}M"

    # Parse series
    series_pattern = re.compile(r'series\s+([A-F])', re.I)
    for match in series_pattern.finditer(text):
        round_name = f"Series {match.group(1).upper()}"
        if round_name not in [r for r in output["funding_rounds"]]:
            output["funding_rounds"].append(round_name)

    # Parse employee count
    emp_pattern = re.compile(r'(\d{2,5})\s*employees', re.I)
    emp_match = emp_pattern.search(text)
    if emp_match:
        output["employees"] = int(emp_match.group(1))

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.crunchbase_lite <company_name>")
        sys.exit(1)
    result = fetch_funding(sys.argv[1])
    print(json.dumps(result, indent=2))
