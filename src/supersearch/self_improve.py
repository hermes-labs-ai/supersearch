"""
SuperSearch self-improvement loop.

Runs a fixed slate of meta-queries about web scraping / search-engine
techniques, parses the returned snippets for actionable phrases (rotate UA,
randomize headers, captcha bypass, new engines, etc.), and writes a Markdown
report. Each report ends with a `## Triggers` section listing concrete upgrade
prompts Claude (or a human) can act on.

Cost: $0. Pure SuperSearch + local parsing. No LLM required.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .search import SearchResult


META_QUERIES: tuple[str, ...] = (
    "web scraping anti-detection techniques 2026",
    "rotate user agent headers Python requests",
    "free search engine APIs no API key",
    "alternative search engines scrapable Startpage Ecosia Marginalia Wiby",
    "bypass cloudflare bot detection open source",
    "TLS fingerprint evasion curl-impersonate",
    "metasearch SearXNG self-hosted",
    "captcha solving open source",
    "headless browser stealth playwright puppeteer",
    "academic search APIs free arXiv Semantic Scholar OpenAlex",
)

# Heuristic patterns we look for in result snippets / titles.
# Each rule maps a regex to a short trigger phrase.
TRIGGER_RULES: tuple[tuple[str, str], ...] = (
    (
        r"(?i)\brotat\w*\s+(user[- ]?agent|ip|proxy|header)\b",
        "Rotate UA / IP / headers",
    ),
    (r"(?i)\b(random|jitter|delay|throttl)\w*", "Randomize delays / throttle"),
    (
        r"(?i)\b(curl[-_ ]?impersonate|tls fingerprint|ja3|ja4)\b",
        "TLS / JA3 fingerprint evasion",
    ),
    (r"(?i)\b(playwright|puppeteer)[- ]?stealth\b", "Headless browser stealth plugin"),
    (r"(?i)\bcloudflare\b.*\b(bypass|solve|evad)\w*", "Cloudflare bypass technique"),
    (r"(?i)\bcaptcha\b.*\b(solv|bypass)\w*", "CAPTCHA solver integration"),
    (
        r"(?i)\b(searxng|metager|marginalia|wiby|kagi|ecosia|startpage|qwant|swisscows|presearch)\b",
        "Candidate engine to integrate",
    ),
    (
        r"(?i)\b(openalex|core\.ac\.uk|crossref|pubmed|s2|semantic scholar)\b",
        "Academic API to integrate",
    ),
    (r"(?i)\b(robots\.txt|crawl-delay|sitemap)\b", "Respect robots.txt / crawl-delay"),
    (r"(?i)\b(referer|referrer)\b.*\b(rotat|random)\w*", "Rotate Referer header"),
)


def _parse_triggers(results: Iterable[SearchResult]) -> dict[str, list[str]]:
    """Scan snippets/titles for trigger patterns. Returns {trigger: [example URLs]}.

    Each URL is recorded once per trigger. Sorted by trigger label for stable
    report output.
    """
    found: dict[str, list[str]] = {}
    for r in results:
        text = f"{r.title or ''} {r.snippet or ''}"
        if not text.strip():
            continue
        for pattern, label in TRIGGER_RULES:
            if re.search(pattern, text):
                bucket = found.setdefault(label, [])
                if r.url and r.url not in bucket:
                    bucket.append(r.url)
    return found


def _format_report(
    query_results: list[tuple[str, list[SearchResult]]],
    triggers: dict[str, list[str]],
    started_at: datetime,
) -> str:
    """Render the Markdown report."""
    lines: list[str] = []
    lines.append("# SuperSearch self-improvement report")
    lines.append("")
    lines.append(f"- **Run at:** {started_at.isoformat()}")
    lines.append(f"- **Queries:** {len(query_results)}")
    total_results = sum(len(rs) for _, rs in query_results)
    lines.append(f"- **Total results scanned:** {total_results}")
    lines.append(f"- **Triggers detected:** {len(triggers)}")
    lines.append("")

    lines.append("## Queries")
    lines.append("")
    for q, rs in query_results:
        lines.append(f"### `{q}`")
        if not rs:
            lines.append("_No results_")
            lines.append("")
            continue
        for r in rs[:5]:
            title = (r.title or "(no title)").strip()
            snippet = (r.snippet or "").strip().replace("\n", " ")[:200]
            lines.append(f"- [{title}]({r.url}) — {snippet}")
        lines.append("")

    lines.append("## Triggers")
    lines.append("")
    if not triggers:
        lines.append("_No upgrade triggers matched in this run._")
    else:
        for label in sorted(triggers):
            urls = triggers[label]
            lines.append(f"### {label}")
            for u in urls[:5]:
                lines.append(f"- {u}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _slugify(label: str) -> str:
    """Lowercase, hyphenate, strip non-[a-z0-9-] — stable file names from trigger labels."""
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "trigger"


def write_trigger_files(
    triggers: dict[str, list[str]],
    triggers_dir: str = "~/.local/state/supersearch/triggers/",
    started_at: Optional[datetime] = None,  # noqa: UP007 — keep optional signature clean
) -> list[str]:
    """Write one Markdown file per trigger under ``triggers_dir``.

    Each file is self-contained and safe to re-run: it carries the trigger
    label, the run timestamp, and the source URLs SuperSearch surfaced.
    Existing files for the same slug are overwritten (reports are frozen
    snapshots — the newest run wins).

    Returns the list of file paths written.
    """
    if started_at is None:
        started_at = datetime.now(timezone.utc)
    base = Path(os.path.expanduser(triggers_dir))
    base.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for label in sorted(triggers):
        urls = triggers[label]
        slug = _slugify(label)
        path = base / f"supersearch-{slug}.md"
        lines = [
            f"# Trigger: {label}",
            "",
            "- **Source:** supersearch --self-improve",
            f"- **Captured:** {started_at.isoformat()}",
            f"- **URLs:** {len(urls)}",
            "",
            "## Evidence",
            "",
        ]
        for u in urls[:10]:
            lines.append(f"- {u}")
        lines.append("")
        lines.append("## Action")
        lines.append("")
        lines.append(
            "Review the evidence above and decide whether to act on this technique. "
            "If implemented, delete this file or move it to the local `triggers/done/` directory."
        )
        lines.append("")
        path.write_text("\n".join(lines))
        written.append(str(path))
    return written


def run_self_improve(
    output_path: str = "~/.local/state/supersearch/self-improve.md",
    max_per_query: int = 5,
    queries: Iterable[str] = META_QUERIES,
    searcher=None,
    sleep_between: float = 0.0,
    write_triggers: bool = False,
    triggers_dir: str = "~/.local/state/supersearch/triggers/",
) -> dict:
    """Execute the self-improvement loop.

    Args:
        output_path: Where to write the Markdown report. ``~`` is expanded.
            Parent directory is created.
        max_per_query: Max results per meta-query.
        queries: Iterable of meta-queries to run. Defaults to ``META_QUERIES``.
        searcher: Optional search backend with ``.search(query, max_results)``.
            Defaults to a fresh ``DuckDuckGoSearch`` (multi-engine via ddgs).
        sleep_between: Seconds to sleep between queries (rate-limit politeness).
        write_triggers: If True, also write one file per detected trigger
            under ``triggers_dir``.
        triggers_dir: Destination for per-trigger files when ``write_triggers``
            is True.

    Returns:
        ``{"output_path": str, "triggers": dict, "queries_run": int,
          "results_total": int, "trigger_files": list[str]}``
    """
    if searcher is None:
        from .search import DuckDuckGoSearch

        searcher = DuckDuckGoSearch(use_cache=True)

    started_at = datetime.now(timezone.utc)
    query_results: list[tuple[str, list[SearchResult]]] = []
    all_results: list[SearchResult] = []

    for q in queries:
        try:
            rs = searcher.search(q, max_results=max_per_query) or []
        except Exception as e:
            print(f"self-improve: query '{q}' failed: {e}")
            rs = []
        query_results.append((q, rs))
        all_results.extend(rs)
        if sleep_between > 0:
            time.sleep(sleep_between)

    triggers = _parse_triggers(all_results)
    report = _format_report(query_results, triggers, started_at)

    out = Path(os.path.expanduser(output_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)

    trigger_files: list[str] = []
    if write_triggers and triggers:
        trigger_files = write_trigger_files(
            triggers, triggers_dir=triggers_dir, started_at=started_at
        )

    return {
        "output_path": str(out),
        "triggers": triggers,
        "queries_run": len(query_results),
        "results_total": len(all_results),
        "trigger_files": trigger_files,
    }
