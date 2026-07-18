# Cross-agent Product V1 trials

All trials used the same clean-installed 0.11.0 wheel and the same three frozen
queries. Every SuperSearch subprocess removed the listed paid/search/model key
environment variables. Codex and Claude still used their own host models to
operate the shell; that host-model usage is not a SuperSearch core requirement
or cost claim.

| Host | Q1 | Q2 | Q3 | Adapter | Disposition |
|---|---|---|---|---|---|
| Generic CLI harness | ok / 6 | ok / 12 | ok / 9 | none | PASS |
| Claude/Fable | ok / 6 | ok / 11 | ok / 9 | none | PASS; selected a useful source for all three |
| Codex, network enabled | ok / 6 | ok / 12 | ok / 9 | none | PARTIAL: three raw SuperSearch receipts are parseable, but the host summary fails the fixed schema and is not a protocol PASS |
| Codex, workspace sandbox | unavailable / 0 | unavailable / 0 | unavailable / 0 | none | Negative-control PASS: DNS denial was explicit for all sources |

Codex's network-enabled structured summary encoded each source object as a JSON
string in `source_states` rather than returning the bare status. Its raw trace
contains three parseable `supersearch.search.v1` receipts and useful selections,
but the summary is schema-invalid and therefore cannot count as a host protocol
PASS. The repaired harness now validates actual host stdout locally and would
fail this historical output. The run is not repeated because the bounded pack
already has two positive hosts (generic and Claude/Fable), while the separate
schema-valid Codex sandbox trial supplies the preregistered failure-honesty
negative control.

The initial host launches also exposed three concrete setup frictions: an old
Codex CLI/default-model mismatch, a Claude schema-draft incompatibility, and a
Codex strict-map schema requirement. They were harness compatibility issues,
not SuperSearch product defects, and their raw stderr is retained.
