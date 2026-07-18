# Privacy, network, and cost model

## Network

SuperSearch is local orchestration, not offline search. It sends the literal
query to each selected service and may send HTTP metadata such as user agent,
IP address, locale, and optional service credentials. DDGS may contact one or
more of its configured web backends. Selected direct adapters contact their
named public services.

Do not submit secrets, private customer data, embargoed claims, credentials, or
regulated data unless the selected services and your own policy permit it.

## Storage

The DDGS wrapper can store result JSON in the user's local SuperSearch cache for
24 hours. Verify has separate local evaluator caches. Product V1 does not run a
SuperSearch telemetry or hosted logging service. Operating-system logs, shell
history, host agents, proxies, and upstream services remain outside that claim.

Set `SUPERSEARCH_CACHE_DIR=/an/isolated/path` to relocate the DDGS result cache
for sandboxes, CI, or disposable evaluations.

## Credentials

The default `ddg,hn,github,arxiv` path does not require a paid API key. GitHub
can use an optional `GITHUB_TOKEN` to improve rate limits; SearXNG uses a
user-supplied service URL. Never place credentials in a query or committed
receipt. SuperSearch does not promise that third-party services accept
unlimited anonymous automation.

## Cost

There is no SuperSearch per-query charge in this open-source candidate. Network,
machine, storage, optional local-model, and third-party service costs still
exist. “No paid key required” is therefore the precise claim; “free” or “zero
cost” is not a universal cost guarantee.
