"""EUR-Lex Official EU Document Connector for SuperSearch."""

import re
import requests
from lxml import html as _lxml_html
from typing import Optional
from xml.etree import ElementTree as ET


class EurLexSource:
    """Connector for EUR-Lex, the Official Journal of the EU.

    Provides search and document fetching for EU regulations and directives.
    """

    BASE_URL = "https://eur-lex.europa.eu"
    SPARQL_URL = "https://publications.europa.eu/webapi/rdf/sparql"
    LEGAL_CONTENT_PATH = "/legal-content/EN/TXT/"

    def __init__(self, timeout: int = 10, max_results: int = 10):
        """Initialize EUR-Lex connector.

        Args:
            timeout: Request timeout in seconds
            max_results: Maximum results per search
        """
        self.timeout = timeout
        self.max_results = max_results
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SuperSearch/1.0)"
        })

    def search(self, query: str, max_results: Optional[int] = None) -> list[dict]:
        """
        Search EUR-Lex for documents matching the query.

        Uses full-text search via SPARQL endpoint and direct CELEX lookups.

        Args:
            query: Search query (e.g., "EU AI Act enforcement")
            max_results: Override default max_results

        Returns:
            List of dicts with keys: title, url, snippet, date, doc_type
        """
        limit = max_results or self.max_results
        results = []

        # Try SPARQL search for relevant keywords
        try:
            results = self._sparql_search(query, limit)
        except Exception as e:
            print(f"SPARQL search failed: {e}")

        # If SPARQL returns nothing, use keyword-based direct lookup
        if not results:
            results = self._direct_search(query, limit)

        return results[:limit]

    def _sparql_search(self, query: str, limit: int) -> list[dict]:
        """Search using EUR-Lex SPARQL endpoint."""
        results = []

        # Build SPARQL query to find documents matching keywords
        # Search across title and subject fields
        keywords = query.split()[:3]  # Use first 3 keywords
        keyword_filter = " || ".join(
            [f"regex(?title, '{kw}', 'i')" for kw in keywords]
        )

        sparql_query = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT DISTINCT ?celex ?title ?date WHERE {{
          ?doc dcterms:identifier ?celex ;
               dcterms:title ?title ;
               dcterms:issued ?date .
          FILTER ({keyword_filter})
          FILTER (CONTAINS(str(?celex), "3"))
        }}
        LIMIT {limit}
        """

        params = {
            "query": sparql_query,
            "format": "application/sparql-results+xml"
        }

        try:
            resp = self.session.post(
                self.SPARQL_URL, data=params, timeout=self.timeout
            )
            resp.raise_for_status()

            # Parse XML response
            root = ET.fromstring(resp.content)

            # Define namespace
            ns = {"sparql": "http://www.w3.org/2005/sparql-results#"}

            celex_xpath = "sparql:binding[@name='celex']/sparql:literal"
            title_xpath = "sparql:binding[@name='title']/sparql:literal"
            date_xpath = "sparql:binding[@name='date']/sparql:literal"

            for result in root.findall(".//sparql:result", ns):
                celex_elem = result.find(celex_xpath, ns)
                title_elem = result.find(title_xpath, ns)
                date_elem = result.find(date_xpath, ns)

                if celex_elem is not None:
                    celex_id = celex_elem.text
                    title = (title_elem.text if title_elem is not None
                             else f"CELEX:{celex_id}")
                    date = date_elem.text if date_elem is not None else None

                    url = (f"{self.BASE_URL}{self.LEGAL_CONTENT_PATH}"
                           f"?uri=CELEX:{celex_id}")

                    results.append({
                        "title": title,
                        "url": url,
                        "snippet": "",
                        "date": date,
                        "doc_type": self._infer_doc_type(title),
                        "celex_id": celex_id,
                    })

        except Exception as e:
            print(f"SPARQL parsing failed: {e}")

        return results

    def _direct_search(self, query: str, limit: int) -> list[dict]:
        """Fall back to direct CELEX lookups for known documents."""
        results = []

        # Map common queries to known CELEX IDs
        known_documents = {
            "AI Act": ("32024R1689", "Regulation 2024/1689 on Artificial Intelligence"),
            "GDPR": ("31995L0046", "Directive 95/46/EC on Data Protection"),
            "NIS Directive": ("32022D1925", "Directive 2022/2555/EU (NIS2)"),
            "Digital Services": ("32022R2065", "Digital Services Act 2022/2065"),
            "DORA": ("32022R2554", "Digital Operational Resilience Act"),
        }

        query_lower = query.lower()
        for keyword, (celex_id, title) in known_documents.items():
            if keyword.lower() in query_lower:
                url = f"{self.BASE_URL}{self.LEGAL_CONTENT_PATH}?uri=CELEX:{celex_id}"
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": f"EU regulatory document on {keyword}",
                    "date": None,
                    "doc_type": self._infer_doc_type(title),
                    "celex_id": celex_id,
                })
                if len(results) >= limit:
                    break

        return results

    def fetch(self, url: str) -> str:
        """
        Fetch the text content of a EUR-Lex document.

        Strips navigation, metadata, and returns clean article text.

        Args:
            url: EUR-Lex document URL

        Returns:
            Clean text content of the document
        """
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()

            tree = _lxml_html.fromstring(resp.text)

            # Strip noise elements in place.
            for tag in tree.xpath("//script|//style|//nav|//header|//footer"):
                parent = tag.getparent()
                if parent is not None:
                    parent.remove(tag)

            # Try EUR-Lex content containers (XPath equivalents of the CSS selectors).
            content = None
            for xpath in [
                "//div[contains(@class, 'oj-doc-body')]",
                "//div[@id='document-body']",
                "//div[contains(@class, 'DocIntro')]",
                "//article[contains(@class, 'document')]",
                "//div[@role='main']",
            ]:
                nodes = tree.xpath(xpath)
                if nodes:
                    content = nodes[0]
                    break

            if content is None:
                body = tree.xpath("//body")
                content = body[0] if body else None

            if content is not None:
                text = "\n".join(
                    t.strip()
                    for t in content.itertext()
                    if t and t.strip()
                )
                text = re.sub(r"\n\s*\n+", "\n\n", text)
                return text.strip()

            return ""

        except Exception as e:
            print(f"Error fetching document: {e}")
            return ""

    def _infer_doc_type(self, title: str) -> str:
        """Infer document type from title."""
        title_lower = title.lower()
        if "regulation" in title_lower:
            return "Regulation"
        elif "directive" in title_lower:
            return "Directive"
        elif "decision" in title_lower:
            return "Decision"
        elif "recommendation" in title_lower:
            return "Recommendation"
        return "Legal Document"
