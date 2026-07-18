"""Fact audit: extract (fact, URL, quote) triples + regex numeric-contradiction
detection + freshness scoring. Spec: ``SCOPE.md`` §Contradiction / §Freshness.

This layer consumes ``SearchResult`` objects (title + snippet + url) and emits:
    - facts: list of {fact, url, exact_quote}
    - contradictions: numeric-disagreement groups (>10% range)
    - freshness: {per_fact: [...], mean: float|None}

Out of scope (v1 per SCOPE.md): NLI, semantic contradiction, entity resolution
beyond exact lowercase match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# -----------------------------------------------------------------------------
# Number extraction
# -----------------------------------------------------------------------------

# Match "1.2M", "500K", "42%", "3.14 billion", "7 years". Captures value + optional unit/suffix.
_NUM_RE = re.compile(
    r"""
    (?P<value>\d+(?:\.\d+)?)
    \s*
    (?P<suffix>%|k|m|b|bn|million|billion|thousand|years?|months?|days?)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SUFFIX_MULTIPLIER = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}


def _normalize_number(value: str, suffix: Optional[str]) -> float:
    """Convert a numeric token + suffix to a float. '1.2M' → 1_200_000.0."""
    try:
        n = float(value)
    except ValueError:
        return 0.0
    if not suffix:
        return n
    key = suffix.lower()
    if key in _SUFFIX_MULTIPLIER:
        return n * _SUFFIX_MULTIPLIER[key]
    return n  # %, years, months, days → keep as-is; comparison only meaningful per-unit


# -----------------------------------------------------------------------------
# Entity extraction (intentionally naive — SCOPE: no entity resolution)
# -----------------------------------------------------------------------------

# Capitalized multi-word spans: "Harvey AI", "OpenAI GPT-4", "Corti Series B".
_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:[ -][A-Z][A-Za-z0-9]*)+)\b")


def _entities(text: str) -> list[str]:
    """Return naive capitalized entity candidates from a snippet."""
    seen: list[str] = []
    for m in _ENTITY_RE.finditer(text or ""):
        ent = m.group(1).strip()
        if ent and ent.lower() not in {e.lower() for e in seen}:
            seen.append(ent)
    return seen


# -----------------------------------------------------------------------------
# Date / freshness extraction
# -----------------------------------------------------------------------------

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_YEAR_ONLY = re.compile(r"\b(19[89]\d|20\d{2})\b")
_RELATIVE = re.compile(
    r"\b(\d+)\s+(day|days|week|weeks|month|months|year|years)\s+ago\b",
    re.IGNORECASE,
)


def extract_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort date extraction. Returns UTC datetime or None."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)

    m = _ISO.search(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:  # noqa: silent — intentional fallback to next regex format
            pass

    m = _US_DATE.search(text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
        except ValueError:  # noqa: silent — intentional fallback to next regex format
            pass

    m = _RELATIVE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {
            "day": 1, "days": 1,
            "week": 7, "weeks": 7,
            "month": 30, "months": 30,
            "year": 365, "years": 365,
        }[unit]
        from datetime import timedelta
        return now - timedelta(days=n * days)

    m = _YEAR_ONLY.search(text)
    if m:
        try:
            return datetime(int(m.group(1)), 1, 1, tzinfo=timezone.utc)
        except ValueError:  # noqa: silent — year-only fallback; unparseable year is OK
            pass

    return None


def freshness_score(dt: Optional[datetime], now: Optional[datetime] = None) -> float:
    """SCOPE §Freshness: 1.0 if <30 days, 0.5 if <1 year, 0.0 otherwise/undetected."""
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    age_days = (now - dt).days
    if age_days < 30:
        return 1.0
    if age_days < 365:
        return 0.5
    return 0.0


# -----------------------------------------------------------------------------
# Fact extraction + contradiction detection
# -----------------------------------------------------------------------------

@dataclass
class Fact:
    fact: str          # one sentence from the snippet containing the numeric claim
    url: str
    exact_quote: str   # the exact substring that supports the fact
    entity: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    date: Optional[str] = None


@dataclass
class Contradiction:
    entity: str
    unit: Optional[str]
    values: list[float]
    urls: list[str]
    span_ratio: float  # (max-min)/min


@dataclass
class FactAudit:
    facts: list[Fact] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    freshness_mean: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "facts": [asdict(f) for f in self.facts],
            "contradictions": [asdict(c) for c in self.contradictions],
            "freshness_mean": self.freshness_mean,
        }


def _first_sentence(snippet: str, match_pos: int) -> str:
    """Return the sentence containing ``match_pos`` in ``snippet``."""
    if not snippet:
        return ""
    start = max(0, snippet.rfind(".", 0, match_pos) + 1)
    end = snippet.find(".", match_pos)
    if end == -1:
        end = len(snippet)
    return snippet[start:end].strip()


# Generic labels we do NOT treat as entities (they're funding-round classes,
# product tiers, etc. — comparing them across sources is meaningless).
_ENTITY_BLOCKLIST = frozenset({
    "series a", "series b", "series c", "series d", "series e",
    "pre seed", "seed round",
})


def _strip_dates(text: str) -> str:
    """Remove ISO + US dates so date digits aren't pulled in as numeric values."""
    text = _ISO.sub("", text or "")
    text = _US_DATE.sub("", text)
    return text


def extract_facts(results) -> list[Fact]:
    """Pull (entity, value, unit, date) facts out of title+snippet pairs.

    Each ``result`` is anything with ``.title``, ``.snippet``, ``.url``
    (e.g. a ``SearchResult`` or dict-like). We extract the date first, then
    strip date tokens before running the numeric regex so date digits aren't
    misread as values.
    """
    facts: list[Fact] = []
    for r in results:
        title = getattr(r, "title", None) or (r.get("title") if isinstance(r, dict) else "") or ""
        snippet = getattr(r, "snippet", None) or (r.get("snippet") if isinstance(r, dict) else "") or ""
        url = getattr(r, "url", None) or (r.get("url") if isinstance(r, dict) else "") or ""
        combined = f"{title}. {snippet}"
        dt = extract_date(combined)

        # Strip dates for numeric extraction only — keep originals for quotes.
        numeric_text = _strip_dates(combined)
        ents = [e for e in _entities(numeric_text) if e.lower() not in _ENTITY_BLOCKLIST]
        primary_entity = ents[0] if ents else None

        for m in _NUM_RE.finditer(numeric_text):
            value_tok = m.group("value")
            suffix = m.group("suffix")
            # Skip bare small integers with no unit — usually noise (counts of "3 days" etc. handled via unit).
            if not suffix and len(value_tok) < 2:
                continue
            value = _normalize_number(value_tok, suffix)
            unit = (suffix or "").lower() if suffix else None
            nearest = primary_entity
            for ent in ents:
                ent_pos = numeric_text.lower().find(ent.lower())
                if 0 <= ent_pos <= m.start() and (m.start() - ent_pos) < 120:
                    nearest = ent
            quote = combined[max(0, m.start() - 40): m.end() + 40].strip()
            facts.append(
                Fact(
                    fact=_first_sentence(combined, m.start()) or quote,
                    url=url,
                    exact_quote=quote,
                    entity=nearest,
                    value=value,
                    unit=unit,
                    date=dt.isoformat() if dt else None,
                )
            )
    return facts


def detect_contradictions(facts: list[Fact]) -> list[Contradiction]:
    """Group by (entity, unit) and flag groups whose numeric span exceeds 10%."""
    groups: dict[tuple[str, Optional[str]], list[Fact]] = {}
    for f in facts:
        if f.entity is None or f.value is None:
            continue
        key = (f.entity.lower(), f.unit)
        groups.setdefault(key, []).append(f)

    contradictions: list[Contradiction] = []
    for (ent_lower, unit), group in groups.items():
        if len(group) < 2:
            continue
        values = [f.value for f in group if f.value is not None]
        if len(values) < 2:
            continue
        lo, hi = min(values), max(values)
        if lo <= 0:
            continue
        span_ratio = (hi - lo) / lo
        if span_ratio > 0.10:
            contradictions.append(
                Contradiction(
                    entity=group[0].entity,  # preserve original casing
                    unit=unit,
                    values=values,
                    urls=[f.url for f in group],
                    span_ratio=round(span_ratio, 4),
                )
            )
    return contradictions


def audit(results, now: Optional[datetime] = None) -> FactAudit:
    """Top-level entry: extract facts, detect contradictions, score freshness."""
    facts = extract_facts(results)
    contradictions = detect_contradictions(facts)

    # Use each fact's pre-computed ISO date first; fall back to re-parsing the
    # quote in case the fact text was truncated.
    scores: list[float] = []
    for f in facts:
        dt = None
        if f.date:
            try:
                dt = datetime.fromisoformat(f.date)
            except ValueError:
                dt = None
        if dt is None:
            dt = extract_date(f.exact_quote)
        if dt is not None:
            scores.append(freshness_score(dt, now=now))
    mean = sum(scores) / len(scores) if scores else None

    return FactAudit(
        facts=facts,
        contradictions=contradictions,
        freshness_mean=mean,
    )


def write_audit_markdown(audit_obj: FactAudit, path: str, query: Optional[str] = None) -> None:
    """Write the fact-audit gate artifact (5 triples + contradictions + freshness)."""
    lines = ["# Fact Audit", ""]
    if query:
        lines.append(f"**Query:** {query}")
        lines.append("")

    top = audit_obj.facts[:5]
    lines.append("## Facts (top 5)")
    lines.append("")
    for i, f in enumerate(top, 1):
        lines.append(f"### {i}. {f.fact or '(no fact extracted)'}")
        lines.append(f"- **URL:** {f.url}")
        lines.append(f"- **Quote:** > {f.exact_quote}")
        if f.entity:
            lines.append(f"- **Entity:** {f.entity}")
        if f.value is not None:
            lines.append(f"- **Value:** {f.value} ({f.unit or 'scalar'})")
        if f.date:
            lines.append(f"- **Date:** {f.date}")
        lines.append("")

    lines.append(f"## Contradictions ({len(audit_obj.contradictions)})")
    lines.append("")
    if not audit_obj.contradictions:
        lines.append("_None detected (SCOPE: numeric ≥10% disagreement only)._")
        lines.append("")
    else:
        for c in audit_obj.contradictions:
            lines.append(f"- **{c.entity}** [{c.unit or 'scalar'}]: values={c.values}, span={c.span_ratio:.1%}")
            for url in c.urls:
                lines.append(f"    - {url}")
            lines.append("")

    lines.append("## Freshness")
    lines.append("")
    if audit_obj.freshness_mean is None:
        lines.append("_No dates extracted._")
    else:
        lines.append(f"Mean freshness: **{audit_obj.freshness_mean:.2f}** (1.0=<30d, 0.5=<1y, 0.0=older)")
    lines.append("")

    with open(path, "w") as fh:
        fh.write("\n".join(lines))
