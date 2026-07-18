# Five-minute SuperSearch Product V1 showcase

## 0:00–0:40 — the job

“SuperSearch is for the moment before analysis: an engineer or agent needs a
useful mix of web, code, community, and research sources, but does not want one
slow source to consume the whole latency budget. It returns search evidence and
availability, not an answer.”

## 0:40–1:20 — clean install truth

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./hermes_supersearch-0.11.0-py3-none-any.whl
supersearch search --version
supersearch search --list-sources
```

Point out that the package distribution is `hermes-supersearch`, while the
import and command are `supersearch`. No model, account, or paid key is needed
for this path.

## 1:20–2:20 — one useful call

```bash
supersearch search \
  "Python 3.12 distutils removal migration setuptools" \
  --sources ddg,hn,github,arxiv \
  --deadline 12 \
  --pretty
```

Show the one JSON document. Read `status`, then the source states, then one
result's `sources`, title, and URL. Do not turn the snippet into a factual claim.

## 2:20–3:15 — failure honesty

Run the deterministic containment control:

```bash
python -m pytest tests/test_sources.py::test_search_all_hung_source_respects_timeout_budget
python -m pytest tests/test_sources.py::test_search_all_structures_completed_empty_and_failed_sources
```

Explain the distinction between completed-empty, failed, and timed-out. A fast
sibling survives a hung source; the receipt becomes `partial` when it still has
results.

## 3:15–4:10 — generic agent use

```bash
python examples/agent_search.py
```

The same JSON works in a shell tool, Python, Codex, Claude/Fable, or any host
that can launch a process. No framework adapter is required.

## 4:10–5:00 — refusal and decision

“SuperSearch does not certify truth, promise exhaustive or uniformly fresh
coverage, or claim that its ranking beats hosted search APIs. Use a single
provider directly when one index is enough; use a hosted research system when
you need managed extraction, synthesis, or an SLA. Use SuperSearch when local,
multi-surface scouting with one deadline and explicit failure state is the job.”

Product recommendation: standalone OSS candidate. Verify is optional. The
Evidence Bridge remains an unpublished `PHASED_COMPONENT_HOLD`, not the product
center and not an integration recommendation.
