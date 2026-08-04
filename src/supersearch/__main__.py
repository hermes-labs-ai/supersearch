"""CLI entry point for SuperSearch."""

import sys
import json
import os
from typing import Any
from .search import DuckDuckGoSearch


def format_result(result: tuple[Any, float], index: int = 1) -> dict:
    """Format a reranked result for output."""
    search_result, score = result
    out = {
        "rank": index,
        "relevance_score": round(score, 4),
        "title": search_result.title,
        "url": search_result.url,
        "snippet": search_result.snippet,
    }
    provenance = getattr(search_result, "sources", None) or []
    if provenance:
        out["sources"] = list(provenance)
    return out


def format_markdown(output: dict) -> str:
    """Render the JSON output as a markdown block for agent consumption."""
    lines: list[str] = []
    lines.append(f"# SuperSearch — {output.get('query', '')}")
    lines.append("")
    summary = output.get("summary")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary.strip())
        lines.append("")
    lines.append(f"## Results ({output.get('total_results', 0)})")
    lines.append("")
    for r in output.get("results", []):
        title = r.get("title") or r.get("url", "")
        url = r.get("url", "")
        score = r.get("relevance_score", 0)
        provenance = r.get("sources") or []
        prov = f" _(via {', '.join(provenance)})_" if provenance else ""
        lines.append(
            f"### {r.get('rank', '?')}. [{title}]({url}) — `{score:.3f}`{prov}"
        )
        snippet = (r.get("snippet") or "").strip()
        if snippet:
            lines.append("")
            lines.append(f"> {snippet}")
        lines.append("")
    extractions = output.get("deep_extractions") or []
    if extractions:
        lines.append("## Deep extractions")
        lines.append("")
        for ext in extractions:
            lines.append(f"### [{ext.get('title', '')}]({ext.get('url', '')})")
            lines.append("")
            lines.append((ext.get("extraction") or "").strip())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print(
            "Usage: supersearch search '<query>' [--pretty] [--sources=ddg,hn,github,arxiv]"
            "\n       supersearch verify '<claim>' [--json] [--max-sources=N] [--deep] [--no-gates]"
            "\n       supersearch '<query>' [legacy options]"
            "\n       legacy: [--deep] [--raw] [--out=<dir>]"
            " [--source=<name>] [--summarize] [--local] [--no-cache]"
            " [--expand] [--cache-clear] [--self-improve]"
            "\n       supersearch research '<topic>' [--depth=N] [--max-pages=N] [--out=<dir>] [--no-gates]"
        )
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    if sys.argv[1] == "search":
        from .search_cli import main as search_main

        exit_code = search_main(sys.argv[2:])
        # A timed-out adapter may leave third-party cleanup hooks behind even
        # though our own worker is daemonized. The CLI contract is stronger than
        # that library lifecycle: once the complete JSON receipt and diagnostics
        # are flushed, close the command process so cleanup cannot extend the
        # advertised caller deadline. In-process Python callers simply return
        # from product.search and keep their host process alive.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        finally:
            os._exit(exit_code)

    # Subcommand dispatch: `supersearch verify <claim>` delegates to
    # supersearch.verify.cli.main. We rewrite sys.argv so argparse inside
    # the verify CLI sees the command as "supersearch verify" (argv[0]) and
    # the claim + flags as the rest.
    if sys.argv[1] == "verify":
        from .verify.cli import main as verify_main

        sys.argv = ["supersearch verify", *sys.argv[2:]]
        sys.exit(verify_main())

    if sys.argv[1] == "research":
        from .research_cli import main as research_main

        sys.argv = ["supersearch research", *sys.argv[2:]]
        sys.exit(research_main())

    # Admin one-shots
    if "--cache-clear" in sys.argv:
        from . import cache as _cache

        n = _cache.clear()
        print(f"Cleared {n} cache entries")
        sys.exit(0)

    if "--self-improve" in sys.argv:
        from .self_improve import run_self_improve

        out_path = "~/.local/state/supersearch/self-improve.md"
        for arg in sys.argv[1:]:
            if arg.startswith("--out="):
                out_path = arg.split("=", 1)[1]
        print("🧠 SuperSearch self-improvement run starting...")
        result = run_self_improve(output_path=out_path)
        print(
            f"✓ {result['queries_run']} queries, {result['results_total']} results scanned"
        )
        print(f"✓ {len(result['triggers'])} upgrade triggers detected")
        print(f"📝 Report: {result['output_path']}")
        if result["triggers"]:
            print("\nTriggers:")
            for label in sorted(result["triggers"]):
                print(f"  • {label}  ({len(result['triggers'][label])} sources)")
        sys.exit(0)

    query = sys.argv[1]
    do_summarize = "--summarize" in sys.argv or "-s" in sys.argv
    use_local = "--local" in sys.argv or "-l" in sys.argv
    do_deep = "--deep" in sys.argv or "-d" in sys.argv
    do_raw = "--raw" in sys.argv or "-r" in sys.argv
    use_cache = "--no-cache" not in sys.argv
    do_expand = "--expand" in sys.argv or "-e" in sys.argv
    do_intelligence = "--intelligence" in sys.argv
    raw_dir = None
    scrape_target = None
    output_format = "json"
    for arg in sys.argv[2:]:
        if arg.startswith("--out="):
            raw_dir = arg.split("=", 1)[1]
        elif arg.startswith("--scrape="):
            scrape_target = arg.split("=", 1)[1]
        elif arg.startswith("--format="):
            output_format = arg.split("=", 1)[1].lower()

    # Scraper mode: run a specific scraper instead of searching
    if scrape_target:
        scraper_map = {
            "github_org": "supersearch.scrapers.github_org",
            "job_board": "supersearch.scrapers.job_board",
            "crunchbase": "supersearch.scrapers.crunchbase_lite",
            "g2_reviews": "supersearch.scrapers.g2_reviews",
            "eu_registry": "supersearch.scrapers.eu_ai_registry",
            "linkedin": "supersearch.scrapers.linkedin_post",
            "youtube": "supersearch.scrapers.youtube_transcript",
            "github_comments": "supersearch.scrapers.github_comments",
            "security_txt": "supersearch.scrapers.security_txt",
            "arxiv_abstract": "supersearch.scrapers.arxiv_abstract",
            "huggingface": "supersearch.scrapers.huggingface_model",
        }
        if scrape_target not in scraper_map:
            print(f"Unknown scraper: {scrape_target}")
            print(f"Available: {', '.join(scraper_map.keys())}")
            sys.exit(1)
        # Re-run the scraper module as a subprocess so its __main__ guard
        # handles arg parsing — simpler than reflecting into the module.
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", scraper_map[scrape_target], query] + sys.argv[3:],
            capture_output=False,
            check=False,
        )
        sys.exit(result.returncode)

    # Source selection: --source hn / --source github / --source arxiv / --source all
    source = "multi"
    for arg in sys.argv[2:]:
        if arg.startswith("--source="):
            source = arg.split("=", 1)[1]
        elif arg == "--source" and sys.argv.index(arg) + 1 < len(sys.argv):
            idx = sys.argv.index(arg)
            source = sys.argv[idx + 1]

    print(f"🔍 Searching for: {query} [{source}]\n")

    # Search
    if do_intelligence:
        from . import routing
        from .sources import search_all

        routed = routing.route(query)
        print(f"🧠 Intelligence routing → {routed}\n")
        results = search_all(query, sources=routed, max_per_source=3)
        searcher = DuckDuckGoSearch(
            backend="auto", use_cache=use_cache
        )  # for --expand/raw fetches
    elif source == "all":
        from .sources import search_all

        results = search_all(query, max_per_source=3)
    elif source == "hn":
        from .sources import HackerNewsSearch

        searcher = HackerNewsSearch()
        results = searcher.search(query, max_results=5)
    elif source == "github":
        from .sources import GitHubSearch

        searcher = GitHubSearch()
        results = searcher.search(query, max_results=5)
    elif source == "arxiv":
        from .sources import ArxivSearch

        searcher = ArxivSearch()
        results = searcher.search(query, max_results=5)
    elif source == "semantic_scholar":
        from .sources import SemanticScholarSearch

        searcher = SemanticScholarSearch()
        results = searcher.search(query, max_results=5)
    elif source in ("twitter", "x"):
        from .sources import TwitterSearch

        searcher = TwitterSearch()
        results = searcher.search(query, max_results=5)
    elif source == "marginalia":
        from .sources import MarginaliaSearch

        searcher = MarginaliaSearch()
        results = searcher.search(query, max_results=5)
    elif source == "wiby":
        from .sources import WibySearch

        searcher = WibySearch()
        results = searcher.search(query, max_results=5)
    elif source == "qwant":
        from .sources import QwantSearch

        searcher = QwantSearch()
        results = searcher.search(query, max_results=5)
    elif source == "ecosia":
        from .sources import EcosiaSearch

        searcher = EcosiaSearch()
        results = searcher.search(query, max_results=5)
    elif source == "startpage":
        from .sources import StartpageSearch

        searcher = StartpageSearch()
        results = searcher.search(query, max_results=5)
    elif source == "ddg":
        searcher = DuckDuckGoSearch(backend="duckduckgo", use_cache=use_cache)
        results = searcher.search(query, max_results=5)
    else:
        # Default: multi-engine (Brave, DDG, Bing, Yahoo, Mojeek, Yandex)
        searcher = DuckDuckGoSearch(backend="auto", use_cache=use_cache)
        results = searcher.search(query, max_results=10)

    # Query expansion: generate variants, run each, dedupe by URL.
    if do_expand and source not in ("all",):
        from .expand import expand_query, dedupe_results

        variants = expand_query(query)
        if variants:
            print(f"🧬 Query expansion: {len(variants)} variants")
            for v in variants:
                print(f"   + {v}")
                extra = searcher.search(v, max_results=5)
                results = dedupe_results([results, extra])

    if not results:
        print("❌ No results found")
        sys.exit(1)

    print(f"✓ Found {len(results)} results")
    print("📊 Re-ranking by relevance...\n")

    # Re-rank
    from .rerank import LocalReranker

    reranker = LocalReranker()
    reranked = reranker.rerank(query, results)

    # Format results
    formatted = [format_result(r, i) for i, r in enumerate(reranked, 1)]

    # Raw mode: fetch top pages, dump clean text to files. No model. Scout only.
    if do_raw:
        import hashlib

        out = raw_dir or "/tmp/supersearch-raw"
        os.makedirs(out, exist_ok=True)
        fetcher = DuckDuckGoSearch()
        top_urls = [(r["title"], r["url"]) for r in formatted[:10]]
        print(f"📥 Raw mode: fetching {len(top_urls)} pages to {out}/\n")
        for title, url in top_urls:
            print(f"  📄 {url[:80]}...")
            page_text = fetcher.fetch_content(url, max_chars=200000)
            if page_text:
                slug = hashlib.md5(url.encode()).hexdigest()[:10]
                filepath = os.path.join(out, f"{slug}.txt")
                with open(filepath, "w") as f:
                    f.write(f"URL: {url}\nTITLE: {title}\n\n{page_text}")
                size = len(page_text)
                print(f"  ✓ {size:,} chars → {filepath}")
            else:
                print("  ⚠️  Could not fetch")
        print(f"\n📁 Raw pages saved to {out}/")
        # Still output JSON with results (no summary in raw mode)
        output = {
            "query": query,
            "total_results": len(reranked),
            "mode": "raw",
            "raw_dir": out,
            "results": formatted,
        }
        print(json.dumps(output, indent=2))
        return

    # Deep mode: fetch top pages and extract structured data BEFORE summarizing
    page_extractions = []
    if do_deep:
        fetcher = DuckDuckGoSearch()
        top_urls = [(r["title"], r["url"]) for r in formatted[:5]]
        print(f"🔎 Deep mode: fetching {len(top_urls)} pages...\n")
        for title, url in top_urls:
            print(f"  📄 Fetching: {url[:80]}...")
            page_text = fetcher.fetch_content(url, max_chars=8000)
            if page_text:
                from .summarize import extract_with_ollama

                print("  🧠 Extracting data...")
                extraction = extract_with_ollama(query, title, url, page_text)
                if extraction and extraction.get("extraction", "").strip():
                    page_extractions.append(extraction)
                else:
                    print("  ⚠️  No useful data extracted")
            else:
                print("  ⚠️  Could not fetch")
        print()

    # Build summarization input — include deep extractions if available
    top_results = [
        {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
        for r in formatted[:3]
    ]
    if page_extractions:
        for ext in page_extractions:
            top_results.append(
                {
                    "title": ext["title"],
                    "url": ext["url"],
                    "snippet": ext["extraction"][:500],
                }
            )

    if use_local:
        from .summarize import summarize_with_ollama

        print("🧠 Summarizing with local model (free)...\n")
        summary = summarize_with_ollama(query, top_results)
    else:
        from .summarize import summarize_with_ollama, summarize_with_haiku_subagent

        if do_summarize:
            print("🧠 Generating Haiku subagent prompt...\n")
            summary = summarize_with_haiku_subagent(query, top_results)
        else:
            print("🧠 Summarizing with local model...\n")
            summary = summarize_with_ollama(query, top_results)

    output = {
        "query": query,
        "total_results": len(reranked),
        "summary": summary.get("answer", summary.get("task", "")),
        "scaffold": summary.get("scaffold", ""),
        "model": summary.get("model", "local"),
        "cost": summary.get("cost", "$0.00"),
        "results": formatted,
    }
    if page_extractions:
        output["deep_extractions"] = page_extractions

    if output_format == "markdown":
        print(format_markdown(output))
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
