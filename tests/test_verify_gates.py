"""Package-owned offline integrity gate tests."""

from __future__ import annotations

import inspect
from pathlib import Path

from supersearch.verify import gates
from supersearch.verify.gates import run_reality_gates
from supersearch.verify.pipeline import FreshnessSummary, SourceVerdict, VerifyResult


def _result(verdict="SUPPORTED", evaluator="ok"):
    snippet = "Bound evidence"
    source = SourceVerdict(
        url="https://example.org/evidence",
        title="Evidence",
        engines=["ddg"],
        query_variant="claim",
        search_snippet=snippet,
        evidence_kind="search_snippet",
        fetch_status="not_requested",
        evidence_excerpt=snippet,
        evidence_sha256="b" * 64,
        nli_label="ENTAIL",
        nli_status=evaluator,
    )
    return VerifyResult(
        claim="claim",
        verdict=verdict,
        verdict_reason="entailment_dominant"
        if verdict == "SUPPORTED"
        else "evaluator_unavailable",
        retrieval_status="ok",
        evaluator_status=evaluator,
        sources=[source],
        freshness=FreshnessSummary("2026-07-18", 0, 1, None),
    )


def test_package_owned_gate_accepts_bound_receipt():
    result = run_reality_gates(_result())
    assert result.ok
    assert all(check.ok for check in result.checks)


def test_gate_rejects_unbound_snippet_excerpt():
    result = _result()
    result.sources[0].evidence_excerpt = "not in the snippet"
    gate = run_reality_gates(result)
    assert not gate.ok
    assert any(check.name == "source_binding" and not check.ok for check in gate.checks)


def test_gate_rejects_positive_when_evaluator_unavailable():
    gate = run_reality_gates(_result(evaluator="unavailable"))
    assert not gate.ok
    assert any(
        check.name == "availability_veto" and not check.ok for check in gate.checks
    )


def test_gate_accepts_conflict_just_above_unrounded_threshold():
    result = _result(verdict="CONFLICTING")
    result.verdict_reason = "numeric_conflict"
    result.numeric_conflicts = [
        {
            "entity": "Alpha",
            "unit": "scalar",
            "values": [100.0, 110.004],
            "span_ratio": 0.10004,
            "evidence": [
                {"url": "https://a.example.org"},
                {"url": "https://b.example.org"},
            ],
        }
    ]
    assert run_reality_gates(result).ok


def test_verify_package_has_no_ambient_script_or_checkout_dependency():
    root = Path(inspect.getfile(gates)).resolve().parent
    body = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "~" + "/ai-" + "infra" not in body
    assert "/Users/" not in body
    assert "subprocess" not in body
