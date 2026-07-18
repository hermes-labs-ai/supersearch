"""Live intelligence integration test.

Only runs with ``pytest --intelligence`` (see conftest.py). Requires a running
Ollama instance with ``nomic-embed-text`` so the routing layer can embed the
query against category seeds.

The test confirms the end-to-end intelligence path is wired up correctly:
    query → routing.route → chosen engines is non-empty and well-formed.

We do NOT hit external search engines here — routing is pure (query →
embedding → engine list), so it's safe and fast once Ollama is warm.
"""

from __future__ import annotations

import pytest

from supersearch import routing


@pytest.mark.intelligence_live
def test_live_routing_returns_nonempty_engines_for_security_query():
    query = "CVE 2024 remote code execution vulnerability patched"
    engines = routing.route(query)
    assert isinstance(engines, list)
    assert len(engines) >= 2, f"expected >=2 engines from routing, got {engines}"
    # Every engine name must be in the canonical map
    all_known = {e for engines_list in routing.CATEGORY_ENGINES.values() for e in engines_list}
    unknown = [e for e in engines if e not in all_known]
    assert not unknown, f"routing returned unknown engines: {unknown}"


@pytest.mark.intelligence_live
def test_live_routing_distinct_engine_sets_across_queries():
    """Parallel of the Task 2 gate, but run live through real Ollama."""
    queries = [
        "peer-reviewed paper on neural network optimization",
        "CVE 2024 remote code execution vulnerability",
        "best sourdough bread recipe beginner",
    ]
    sets = [tuple(routing.route(q)) for q in queries]
    assert len(set(sets)) >= 2, f"expected >=2 distinct engine sets, got {sets}"
