# Bounded alternative research

Retrieved 2026-07-18 from official project/vendor documentation and primary
package pages. This is a defensible-dimension comparison, not a general market
ranking.

| Alternative | Keys/cost | Hosted/model posture | Breadth and agent surface | Install/license | What this means for SuperSearch |
|---|---|---|---|---|---|
| [DDGS](https://pypi.org/project/ddgs/) | Base usage documents no API key or paid plan | Local Python client to public search services; no LLM required | Multiple web backends plus text/news/images/video/books; CLI, API, and MCP are documented | `pip install ddgs`; MIT | Free metasearch alone is not a differentiator. SuperSearch must add heterogeneous direct-source fan-out, one total deadline, and explicit source status/provenance. |
| [SearXNG](https://docs.searxng.org/dev/search_api.html) | Self-hosted; individual engines have their own policies | Local/self-hosted metasearch service; no LLM inherent | Broad configurable engines and JSON/CSV/RSS API, though public instances may disable formats | Container/script/manual server installation; AGPL-3.0-or-later in the primary repository | Broader operator-controlled metasearch, but a much heavier service. SuperSearch should remain a library/CLI with no daemon. |
| [Tavily](https://docs.tavily.com/documentation/quickstart) | Account/API key; 1,000 free credits monthly, then metered plans | Hosted search/extract/crawl/research API; answer generation is optional | Agent-oriented SDK/API with filtering, recency, and extracted content | Small SDK install; hosted proprietary service | Better managed-service polish. SuperSearch offers a zero-account path and local orchestration, not equivalent hosted relevance or SLA claims. |
| [Exa](https://exa.ai/pricing?tab=api) | Hosted free tier and metered endpoint pricing | Hosted AI search/crawl/research service | Search, contents, monitors, answer, and agent endpoints | Hosted proprietary service | SuperSearch cannot claim equivalent index quality or latency. Its wedge is inspectable local fan-out without a paid credential or hosted-model dependency. |
| [Firecrawl](https://docs.firecrawl.dev/api-reference/endpoint/search) | Every API request requires an API key; plan credits apply | Hosted search plus optional page scraping/agentic features | Web search can include scraped content and GitHub/research/PDF categories | SDK or HTTP API; hosted service terms | Strong extraction workflow; SuperSearch keeps extraction optional and focuses on source identity plus deadline containment. |

## Comparison dimensions not established

The sources above do not support a controlled cross-product relevance or truth
comparison. SuperSearch therefore makes no superiority claim about index size,
ranking quality, factual accuracy, uptime, or end-to-end research quality.

## Distribution name check

PyPI already has a case-insensitive [`Super-Search`](https://pypi.org/project/Super-Search/)
distribution for a filesystem-search utility. A public release should retain
the `supersearch` import and CLI but use a distinct distribution name such as
`hermes-supersearch`, after a final availability and naming check immediately
before publication. No package or public repository is created by this work.

