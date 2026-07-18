"""EU AI Act registration database tracker. Stub — database not yet launched."""

import json
import sys


def check_registry(company_name):
    """Check EU AI Act high-risk AI system registration database.

    NOTE: The official EU database (Article 71) is not yet operational as of April 2026.
    This stub returns a placeholder. When the database launches, implement scraping here.
    """
    return {
        "company": company_name,
        "status": "database_not_launched",
        "note": "EU AI Act Article 71 database expected to be operational by August 2, 2026. "
                "Monitor: https://artificialintelligenceact.eu/",
        "registered_systems": [],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m supersearch.scrapers.eu_ai_registry <company_name>")
        sys.exit(1)
    result = check_registry(sys.argv[1])
    print(json.dumps(result, indent=2))
