"""Human and machine formatters for the Verify V1 evidence receipt."""

from __future__ import annotations

import json

from .pipeline import VerifyResult, result_as_dict


def format_json(result: VerifyResult) -> str:
    """Serialize the stable ``supersearch.verify.v1`` receipt schema."""
    return json.dumps(result_as_dict(result), indent=2, ensure_ascii=False)


def _format_freshness(result: VerifyResult) -> str:
    freshness = result.freshness
    if freshness is None or freshness.mean is None:
        total = freshness.total_sources if freshness else len(result.sources)
        return f"n/a (0/{total} sources dated)"
    return (
        f"{freshness.mean:.2f} ({freshness.dated_sources}/{freshness.total_sources} "
        f"sources dated; as of {freshness.as_of})"
    )


def format_markdown(result: VerifyResult) -> str:
    """Render a legible receipt without hiding evidence limitations."""
    lines = [
        f"# supersearch verify: {result.verdict}",
        "",
        f"**Claim:** {result.claim}",
        f"**Reason:** {result.verdict_reason}",
        f"**Retrieval:** {result.retrieval_status}",
        f"**Evaluator:** {result.evaluator_status}",
        f"**Deep requested:** {'yes' if result.deep_requested else 'no'}",
        f"**Sources:** {len(result.sources)}",
        f"**Freshness:** {_format_freshness(result)}",
        f"**Cost:** ${result.cost_usd:.2f}",
    ]
    if result.engines_used:
        lines.append(f"**Engines:** {', '.join(result.engines_used)}")
    lines.extend(["", "## Evidence", ""])

    if not result.sources:
        lines.append("_No sources retrieved._")
    else:
        for index, source in enumerate(result.sources, 1):
            lines.extend(
                [
                    f"### {index}. [{source.nli_label}] {source.title or '(untitled)'}",
                    f"- **URL:** {source.url}",
                    f"- **Evidence provenance:** `{source.evidence_kind}`",
                    f"- **Fetch status:** `{source.fetch_status}`",
                    f"- **Evaluator status:** `{source.nli_status}`",
                ]
            )
            if source.engines:
                lines.append(f"- **Retrieved via:** {', '.join(source.engines)}")
            if source.query_variant:
                lines.append(f"- **Query:** {source.query_variant}")
            if source.date:
                lines.append(
                    f"- **Detected date:** {source.date} ({source.date_basis}; heuristic)"
                )
            lines.extend(
                [
                    f"- **Evidence SHA-256:** `{source.evidence_sha256}`",
                    "- **Evidence excerpt:**",
                    f"> {source.evidence_excerpt}",
                    "",
                ]
            )

    lines.extend(["## Numeric conflicts", ""])
    if not result.numeric_conflicts:
        lines.extend(["_None detected (>10% heuristic across distinct URLs)._", ""])
    else:
        for conflict in result.numeric_conflicts:
            unit = conflict.get("unit") or "scalar"
            lines.append(
                f"- **{conflict.get('entity', '(unknown)')}** [{unit}]: "
                f"values={conflict.get('values', [])}, "
                f"span={float(conflict.get('span_ratio', 0.0)):.1%}"
            )
            for item in conflict.get("evidence", []):
                lines.append(
                    f"    - {item.get('value')} — {item.get('url')} "
                    f"(`{item.get('evidence_kind')}`): {item.get('evidence_excerpt')}"
                )
            lines.append("")

    if result.limitations:
        lines.extend(["## Limits", ""])
        lines.extend(f"- {item}" for item in result.limitations)
        lines.append("")

    lines.extend(["## Nonclaims", ""])
    lines.extend(f"- {item}" for item in result.nonclaims)
    return "\n".join(lines).rstrip() + "\n"
