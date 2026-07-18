"""Framework-neutral SuperSearch Product V1 example."""

import json

from supersearch import fanout_search


receipt = fanout_search(
    "Python 3.12 distutils removal migration setuptools",
    sources=["ddg", "hn", "github", "arxiv"],
    deadline_seconds=12,
)

print(json.dumps(receipt, indent=2))

if receipt["status"] == "unavailable":
    raise SystemExit(3)

for source in receipt["sources"]:
    if source["status"] != "completed":
        print(
            f"source warning: {source['name']}={source['status']}",
            file=__import__("sys").stderr,
        )
