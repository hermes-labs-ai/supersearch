"""Truthful, source-bound claim verification pipeline."""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

from .nli import ClassificationResult, aggregate, classify_batch_results
from .retrieval import Retrieved, RetrievalResult, retrieve_with_status

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "supersearch.verify.v1"
DEEP_TOP_K = 5
DEEP_FETCH_CHARS = 4000
DEEP_NLI_CHARS = 3000
DEEP_FETCH_TIMEOUT = 15
DEEP_FETCH_WORKERS = 5
EVIDENCE_EXCERPT_CHARS = 320

NONCLAIMS = [
    "This receipt does not establish ground truth, factual accuracy, certification, completeness, or source authority.",
    "A search snippet is not a quote verified against the live page.",
    "A listed URL does not prove current reachability.",
    "Detected dates are heuristic and may not be authoritative publication dates.",
    "Numeric disagreement is a syntactic signal, not proof of semantic contradiction.",
    "Listed sources are not asserted to be independent.",
]


@dataclass
class SourceVerdict:
    url: str
    title: str
    engines: list[str]
    query_variant: str
    search_snippet: str
    evidence_kind: str  # search_snippet | fetched_page
    fetch_status: str  # not_requested | fetched | failed | not_attempted
    evidence_excerpt: str
    evidence_sha256: str
    nli_label: str  # ENTAIL | CONTRADICT | NEUTRAL
    nli_status: str
    date: str | None = None
    date_basis: str | None = None
    freshness_score: float | None = None

    @property
    def snippet(self) -> str:
        """Compatibility alias; new receipts serialize ``search_snippet``."""
        return self.search_snippet

    @property
    def exact_quote(self) -> str:
        """Compatibility alias; provenance lives in ``evidence_kind``."""
        return self.evidence_excerpt


@dataclass
class FreshnessSummary:
    as_of: str
    dated_sources: int
    total_sources: int
    mean: float | None


@dataclass
class VerifyResult:
    claim: str
    verdict: str
    verdict_reason: str
    schema_version: str = SCHEMA_VERSION
    retrieval_status: str = "not_run"
    evaluator_status: str = "not_run"
    deep_requested: bool = False
    sources: list[SourceVerdict] = field(default_factory=list)
    numeric_conflicts: list[dict] = field(default_factory=list)
    freshness: FreshnessSummary | None = None
    engines_used: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    nonclaims: list[str] = field(default_factory=lambda: list(NONCLAIMS))
    cost_usd: float = 0.0

    @property
    def contradictions(self) -> list[dict]:
        """Compatibility alias for the v0 receipt API."""
        return self.numeric_conflicts

    @property
    def freshness_mean(self) -> float | None:
        return self.freshness.mean if self.freshness else None


@dataclass(frozen=True)
class _EvidenceInput:
    text: str
    kind: str
    fetch_status: str
    content_hash: str | None


def _literal_excerpt(
    text: str, claim: str, max_len: int = EVIDENCE_EXCERPT_CHARS
) -> str:
    """Return a claim-adjacent literal slice without synthetic punctuation."""
    source = (text or "").strip()
    if len(source) <= max_len:
        return source
    tokens = sorted(
        {t for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]*", claim) if len(t) >= 4},
        key=len,
        reverse=True,
    )
    lower = source.lower()
    positions = [lower.find(token.lower()) for token in tokens]
    positions = [pos for pos in positions if pos >= 0]
    anchor = min(positions) if positions else 0
    start = max(0, anchor - max_len // 4)
    end = min(len(source), start + max_len)
    if end - start < max_len:
        start = max(0, end - max_len)
    return source[start:end].strip()


def _run_fact_audit(records: list[Retrieved]):
    try:
        from supersearch.fact_audit import audit

        return audit(records)
    except Exception as e:  # pragma: no cover - defensive dependency seam
        logger.warning("fact_audit failed (%s); numeric signal unavailable", e)
        return None


def _claim_relevant(entity: str | None, claim: str) -> bool:
    return bool(entity and entity.lower() in claim.lower())


def _numeric_conflicts(claim: str, fact_audit, records: list[Retrieved]) -> list[dict]:
    """Return claim-bound >10% conflicts with per-value snippet provenance."""
    if fact_audit is None:
        return []
    out: list[dict] = []
    snippets_by_url = {record.url: record.snippet for record in records}
    for conflict in fact_audit.contradictions:
        if not _claim_relevant(conflict.entity, claim):
            continue
        matching = []
        seen: set[tuple[str, float]] = set()
        for fact in fact_audit.facts:
            if not fact.url or fact.value is None:
                continue
            if (fact.entity or "").lower() != conflict.entity.lower():
                continue
            if fact.unit != conflict.unit:
                continue
            key = (fact.url, float(fact.value))
            if key in seen:
                continue
            seen.add(key)
            matching.append(fact)
        facts_by_url: dict[str, list] = {}
        for fact in matching:
            facts_by_url.setdefault(fact.url, []).append(fact)
        # The regex audit cannot disambiguate two same-entity/unit values on one
        # page (for example, historical versus current figures). Exclude that
        # URL rather than manufacture a cross-source disagreement from it.
        matching = [
            facts[0]
            for url, facts in sorted(facts_by_url.items())
            if len(facts) == 1
        ]
        cross_url_pairs = []
        for index, left in enumerate(matching):
            for right in matching[index + 1 :]:
                if left.url == right.url:
                    continue
                left_value, right_value = float(left.value), float(right.value)
                lo, hi = sorted((left_value, right_value))
                if lo <= 0:
                    continue
                low_fact, high_fact = (
                    (left, right) if left_value <= right_value else (right, left)
                )
                cross_url_pairs.append(
                    ((hi - lo) / lo, lo, hi, low_fact, high_fact)
                )
        if not cross_url_pairs:
            continue
        span_ratio, lo, hi, low_fact, high_fact = max(
            cross_url_pairs,
            key=lambda item: (
                item[0],
                item[2],
                -item[1],
                item[3].url,
                item[4].url,
            ),
        )
        if span_ratio <= 0.10:
            continue
        conflicting_facts = [low_fact, high_fact]
        out.append(
            {
                "entity": conflict.entity,
                "unit": conflict.unit,
                "values": [lo, hi],
                "span_ratio": span_ratio,
                "rule": ">10% across at least two distinct URLs",
                "evidence": [
                    {
                        "value": float(fact.value),
                        "url": fact.url,
                        "evidence_excerpt": (
                            fact.exact_quote
                            if fact.exact_quote in snippets_by_url.get(fact.url, "")
                            else _literal_excerpt(
                                snippets_by_url.get(fact.url, ""), conflict.entity
                            )
                        ),
                        "evidence_kind": "search_snippet",
                    }
                    for fact in conflicting_facts
                ],
            }
        )
    return out


def _fetch_one(url: str, max_chars: int, timeout: int) -> str | None:
    """Fetch one page while keeping dependency noise off JSON stdout."""
    try:
        from supersearch.search import DuckDuckGoSearch

        return DuckDuckGoSearch().fetch_content(
            url, timeout=timeout, max_chars=max_chars
        )
    except Exception as e:  # pragma: no cover - defensive network seam
        logger.debug("verify --deep: fetch_content(%s) failed: %s", url, e)
        return None


def _deep_fetch_top(
    records: list[Retrieved],
    top_k: int = DEEP_TOP_K,
    max_chars: int = DEEP_FETCH_CHARS,
    timeout: int = DEEP_FETCH_TIMEOUT,
    max_workers: int = DEEP_FETCH_WORKERS,
) -> dict[int, str]:
    if not records:
        return {}
    targets = list(enumerate(records[:top_k]))
    out: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_one, r.url, max_chars, timeout): i for i, r in targets
        }
        for future, index in futures.items():
            try:
                text = future.result(timeout=timeout + 2)
            except (FutTimeoutError, Exception) as e:  # noqa: PERF203
                logger.debug("verify --deep: fetch[%d] failed: %s", index, e)
                continue
            if text and text.strip():
                out[index] = text
    return out


def _rerank_for_deep(claim: str, records: list[Retrieved]) -> list[Retrieved]:
    try:
        from supersearch.rerank import LocalReranker
        from supersearch.search import SearchResult

        adapters = [
            SearchResult(
                title=record.title,
                url=record.url,
                snippet=record.snippet,
                sources=list(record.engines),
            )
            for record in records
        ]
        reranked = LocalReranker().rerank(claim, adapters)
        by_url = {record.url: record for record in records}
        out = [
            by_url[result.url] for result, _score in reranked if result.url in by_url
        ]
        seen = {record.url for record in out}
        out.extend(record for record in records if record.url not in seen)
        return out
    except Exception as e:  # pragma: no cover - offline embedding seam
        logger.debug("verify --deep: rerank failed (%s); using retrieval order", e)
        return list(records)


def _evidence_inputs(records: list[Retrieved], deep: bool) -> list[_EvidenceInput]:
    fetched = _deep_fetch_top(records) if deep else {}
    out: list[_EvidenceInput] = []
    for index, record in enumerate(records):
        if deep and index < DEEP_TOP_K:
            page = fetched.get(index)
            if page and page.strip():
                text = page[:DEEP_NLI_CHARS]
                digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
                out.append(_EvidenceInput(text, "fetched_page", "fetched", digest))
            else:
                out.append(
                    _EvidenceInput(record.snippet, "search_snippet", "failed", None)
                )
        elif deep:
            out.append(
                _EvidenceInput(record.snippet, "search_snippet", "not_attempted", None)
            )
        else:
            out.append(
                _EvidenceInput(record.snippet, "search_snippet", "not_requested", None)
            )
    return out


def _normalize_as_of(as_of: datetime | date | None) -> datetime:
    if as_of is None:
        return datetime.now(timezone.utc)
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            return as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc)
    return datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)


def _attach_freshness(
    sources: list[SourceVerdict],
    records: list[Retrieved],
    evidence: list[_EvidenceInput],
    as_of: datetime,
) -> FreshnessSummary:
    try:
        from supersearch.fact_audit import extract_date, freshness_score
    except ImportError:  # pragma: no cover
        return FreshnessSummary(as_of.date().isoformat(), 0, len(sources), None)
    scores: list[float] = []
    for source, record, basis in zip(sources, records, evidence, strict=True):
        detected = extract_date(f"{record.title}. {basis.text}", now=as_of)
        if detected is None or detected > as_of:
            continue
        score = freshness_score(detected, now=as_of)
        source.date = detected.isoformat()
        source.date_basis = basis.kind
        source.freshness_score = score
        scores.append(score)
    mean = sum(scores) / len(scores) if scores else None
    return FreshnessSummary(
        as_of=as_of.date().isoformat(),
        dated_sources=len(scores),
        total_sources=len(sources),
        mean=mean,
    )


def _evaluator_status(results: list[ClassificationResult]) -> str:
    complete = {"ok", "cached"}
    if results and all(result.status in complete for result in results):
        return "ok"
    if results and all(result.status not in complete for result in results):
        return "unavailable"
    return "partial"


def _verdict_reason(verdict: str) -> str:
    return {
        "SUPPORTED": "entailment_dominant",
        "CONTRADICTED": "contradiction_dominant",
        "CONFLICTING": "mixed_evidence",
        "UNVERIFIED": "no_stance_evidence",
    }[verdict]


def verify_claim(
    claim: str,
    max_sources: int = 12,
    deep: bool = False,
    as_of: datetime | date | None = None,
) -> VerifyResult:
    """Create a versioned evidence receipt without availability overclaims."""
    retrieval: RetrievalResult = retrieve_with_status(claim, max_sources=max_sources)
    as_of_dt = _normalize_as_of(as_of)
    if not retrieval.records:
        reason = (
            "retrieval_unavailable"
            if retrieval.status in {"unavailable", "partial"}
            else "no_sources"
        )
        return VerifyResult(
            claim=claim,
            verdict="UNVERIFIED",
            verdict_reason=reason,
            retrieval_status=retrieval.status,
            evaluator_status="not_run",
            deep_requested=deep,
            freshness=FreshnessSummary(as_of_dt.date().isoformat(), 0, 0, None),
            limitations=["No evidence was available for evaluation."],
        )

    records = (
        _rerank_for_deep(claim, retrieval.records) if deep else list(retrieval.records)
    )
    evidence = _evidence_inputs(records, deep)
    classifications = classify_batch_results(
        claim,
        [item.text for item in evidence],
        content_hashes=[item.content_hash for item in evidence],
    )
    evaluator_status = _evaluator_status(classifications)

    sources = [
        SourceVerdict(
            url=record.url,
            title=record.title,
            engines=list(record.engines),
            query_variant=record.query_variant,
            search_snippet=record.snippet,
            evidence_kind=item.kind,
            fetch_status=item.fetch_status,
            evidence_excerpt=_literal_excerpt(item.text, claim),
            evidence_sha256=hashlib.sha256(
                item.text.encode("utf-8", "replace")
            ).hexdigest(),
            nli_label=classification.label,
            nli_status=classification.status,
        )
        for record, item, classification in zip(
            records, evidence, classifications, strict=True
        )
    ]
    freshness = _attach_freshness(sources, records, evidence, as_of_dt)
    fact_audit = _run_fact_audit(records)
    numeric_conflicts = _numeric_conflicts(claim, fact_audit, records)

    labels = [classification.label for classification in classifications]
    base_verdict = aggregate(labels)
    if retrieval.status != "ok":
        verdict = "UNVERIFIED"
        reason = "retrieval_unavailable"
    elif evaluator_status != "ok":
        verdict = "UNVERIFIED"
        reason = "evaluator_unavailable"
    elif numeric_conflicts:
        verdict = "CONFLICTING"
        reason = "numeric_conflict"
    else:
        verdict = base_verdict
        reason = _verdict_reason(verdict)

    engines_used: list[str] = []
    for record in records:
        for engine in record.engines:
            if engine not in engines_used:
                engines_used.append(engine)

    limitations: list[str] = []
    if any(item.kind == "search_snippet" for item in evidence):
        limitations.append(
            "Search-snippet evidence was not verified against fetched page content."
        )
    if any(item.fetch_status == "failed" for item in evidence):
        limitations.append(
            "One or more requested page fetches failed and fell back to search snippets."
        )
    if retrieval.status != "ok":
        limitations.append("Retrieval was incomplete; the top verdict is UNVERIFIED.")
    if evaluator_status != "ok":
        limitations.append(
            "Required evaluator work was incomplete; the top verdict is UNVERIFIED."
        )
    if numeric_conflicts:
        limitations.append(
            "Numeric-conflict detection uses a >10% lexical heuristic across distinct URLs."
        )
    if freshness.dated_sources < freshness.total_sources:
        limitations.append(
            "Freshness covers only sources with a heuristically detected non-future date."
        )

    return VerifyResult(
        claim=claim,
        verdict=verdict,
        verdict_reason=reason,
        retrieval_status=retrieval.status,
        evaluator_status=evaluator_status,
        deep_requested=deep,
        sources=sources,
        numeric_conflicts=numeric_conflicts,
        freshness=freshness,
        engines_used=engines_used,
        limitations=limitations,
    )


def result_as_dict(result: VerifyResult) -> dict:
    """Stable, ordered machine schema independent of dataclass field order."""
    freshness = result.freshness or FreshnessSummary("", 0, len(result.sources), None)
    return {
        "schema_version": result.schema_version,
        "claim": result.claim,
        "verdict": result.verdict,
        "verdict_reason": result.verdict_reason,
        "retrieval_status": result.retrieval_status,
        "evaluator_status": result.evaluator_status,
        "deep_requested": result.deep_requested,
        "sources": [asdict(source) for source in result.sources],
        "numeric_conflicts": list(result.numeric_conflicts),
        "freshness": asdict(freshness),
        "engines_used": list(result.engines_used),
        "limitations": list(result.limitations),
        "nonclaims": list(result.nonclaims),
        "cost_usd": result.cost_usd,
    }
