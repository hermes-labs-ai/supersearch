"""OpenCorporates + SEC EDGAR source connector for M&A/shutdown signals."""

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class CompanySignal:
    """Unified company signal record."""
    name: str
    jurisdiction: str
    status: str  # active, dissolved, inactive, dormant
    source: str  # "opencorp" or "edgar"
    url: str
    date: str | None = None
    signal_type: str | None = None  # shutdown, acquisition, pivot


class OpenCorporatesSource:
    """OpenCorporates API connector for company status queries."""

    API_BASE = "https://api.opencorporates.com/v0.4/companies/search"

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """
        Search OpenCorporates for companies matching query.
        Returns dissolution/inactive status as M&A/shutdown signal.
        """
        params = {
            "q": query,
            "format": "json",
            "per_page": min(max_results, 100),
        }
        url = f"{self.API_BASE}?{urlencode(params)}"

        try:
            req = Request(url, headers={"User-Agent": "SuperSearch/v0.9"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            return [{"error": f"OpenCorporates API unreachable: {e}", "source": "opencorp"}]
        except json.JSONDecodeError as e:
            return [{"error": f"Invalid JSON from OpenCorporates: {e}", "source": "opencorp"}]

        results = []
        companies = data.get("results", {}).get("companies", [])

        for company in companies[:max_results]:
            record = {
                "name": company.get("name", ""),
                "jurisdiction": company.get("jurisdiction_code", ""),
                "status": company.get("company_status", "unknown"),
                "url": company.get("url", ""),
                "incorporation_date": company.get("incorporation_date"),
                "dissolution_date": company.get("dissolution_date"),
                "source": "opencorp",
            }
            # Flag dissolution/inactive as shutdown signal
            if record["status"] in ("dissolved", "inactive", "dormant"):
                record["signal_type"] = "shutdown"
            results.append(record)

        return results


class SECEdgarSource:
    """SEC EDGAR full-text search connector for acquisition/dissolution signals."""

    EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        """
        Search SEC EDGAR for 8-K filings mentioning acquisitions, dissolutions.
        Returns material event filings.
        """
        params = {
            "q": query,
            "dateRange": "custom",
            "startdt": "2024-01-01",
            "enddt": "2026-04-20",
            "forms": "8-K",  # Material events filing
            "count": min(max_results, 100),
        }
        url = f"{self.EFTS_URL}?{urlencode(params)}"

        try:
            req = Request(url, headers={"User-Agent": "SuperSearch/v0.9"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            return [{"error": f"SEC EDGAR API unreachable: {e}", "source": "edgar"}]
        except json.JSONDecodeError as e:
            return [{"error": f"Invalid JSON from SEC EDGAR: {e}", "source": "edgar"}]

        results = []
        filings = data.get("results", [])

        for filing in filings[:max_results]:
            record = {
                "company": filing.get("company_name", ""),
                "cik": filing.get("cik_str", ""),
                "filing_type": filing.get("form", ""),
                "filing_date": filing.get("filing_date", ""),
                "accession": filing.get("accession_number", ""),
                "url": f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={filing.get('cik_str', '')}&accession_number={filing.get('accession_number', '').replace('-', '')}&xbrl_type=v",
                "snippet": filing.get("snippet", ""),
                "source": "edgar",
                "signal_type": "material_event",  # 8-K = material event
            }
            results.append(record)

        return results


def merge_signals(opencorp_results: list[dict], edgar_results: list[dict]) -> list[CompanySignal]:
    """Merge and deduplicate signals from both sources."""
    seen = set()
    signals = []

    # Process OpenCorporates results
    for r in opencorp_results:
        if "error" in r:
            continue
        key = (r["name"].lower(), r["jurisdiction"])
        if key not in seen:
            seen.add(key)
            signals.append(CompanySignal(
                name=r["name"],
                jurisdiction=r["jurisdiction"],
                status=r["status"],
                source="opencorp",
                url=r["url"],
                signal_type=r.get("signal_type"),
            ))

    # Process SEC EDGAR results
    for r in edgar_results:
        if "error" in r:
            continue
        key = (r["company"].lower(), "US")  # EDGAR is US-centric
        if key not in seen:
            seen.add(key)
            signals.append(CompanySignal(
                name=r["company"],
                jurisdiction="US",
                status="active",  # EDGAR doesn't imply dissolution
                source="edgar",
                url=r["url"],
                date=r["filing_date"],
                signal_type=r.get("signal_type"),
            ))

    return signals
