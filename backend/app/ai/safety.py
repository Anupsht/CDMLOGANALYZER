"""AI safety layer (Phase 8, spec §3).

Every AI-produced explanation — deterministic composer or external LLM —
passes through :func:`validate_explanation` before it is stored or shown:

* the epistemic vocabulary is exactly ``CONFIRMED | PROBABLE | POSSIBLE |
  UNKNOWN`` (anything else degrades to ``UNKNOWN``);
* claims may only reference evidence identifiers that exist in the digest;
* code-like tokens and serial/denomination/amount-like numbers appearing in
  a claim must exist in the digest corpus — anything else is redacted as
  *unverified* and recorded in ``safety_notes``;

The layer can guarantee non-invention only for the deterministic composer;
for an external LLM it is a best-effort filter plus the prompt contract.
Either way the output never presents itself as certain.
"""

from __future__ import annotations

import json

import re

LABELS = ("CONFIRMED", "PROBABLE", "POSSIBLE", "UNKNOWN")

_LABEL_ALIASES = {
    "CONFIRMED": "CONFIRMED",
    "CERTAIN": "CONFIRMED",
    "VERIFIED": "CONFIRMED",
    "PROBABLE": "PROBABLE",
    "LIKELY": "PROBABLE",
    "HIGH": "PROBABLE",
    "POSSIBLE": "POSSIBLE",
    "MAYBE": "POSSIBLE",
    "SPECULATIVE": "POSSIBLE",
    "HYPOTHESIS": "POSSIBLE",
    "UNKNOWN": "UNKNOWN",
    "UNVERIFIED": "UNKNOWN",
    "NOT_CONFIRMED": "UNKNOWN",
}

_CODE_LIKE = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)*[-_]?[0-9]+\b")
# amounts / denominations / serial-like long numbers (not small counters)
_NUMBER_LIKE = re.compile(r"\b\d{3,}(?:\.\d+)?\b|\b\d+\.\d+\b")

_MAX_SUMMARY = 2000
_MAX_CLAIM = 600
_MAX_LIST = 8
_MAX_EVIDENCE = 60


def epistemic_from_confidence(confidence: str | None) -> str:
    """Map rules-engine evidence strength (LOW..VERY_HIGH) to the label set."""
    return {
        "VERY_HIGH": "CONFIRMED",
        "HIGH": "PROBABLE",
        "MODERATE": "POSSIBLE",
        "LOW": "UNKNOWN",
    }.get((confidence or "").upper(), "UNKNOWN")


def _label(value) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    return _LABEL_ALIASES.get(value.strip().upper(), "UNKNOWN")


def _corpus(digest: dict) -> str:
    """Every literal allowed to appear in a claim (facts only)."""
    parts: list[str] = [
        json.dumps(digest.get("transaction") or {}, default=str),
        json.dumps(digest.get("machine") or {}, default=str),
        json.dumps(digest.get("engine_report") or {}, default=str),
    ]
    for item in digest.get("evidence") or []:
        parts.append(item.get("raw_excerpt") or "")
        parts.append(item.get("file") or "")
    for block in ("normalized_events", "host_events", "error_events"):
        parts.append(json.dumps(digest.get(block) or [], default=str))
    parts.append(json.dumps(digest.get("cash_states") or {}, default=str))
    parts.append(json.dumps(digest.get("hardware_events") or {}, default=str))
    parts.append(json.dumps(digest.get("rule_results") or {}, default=str))
    return "\n".join(parts)


def _check_text(text: str, corpus: str, notes: list[str], where: str) -> str:
    """Redact code-like / amount-like tokens that do not exist in the digest."""
    if not isinstance(text, str) or not text:
        return ""
    tokens = set(_CODE_LIKE.findall(text)) | set(_NUMBER_LIKE.findall(text))
    unknown = sorted(t for t in tokens if t not in corpus)
    if not unknown:
        return text
    cleaned = text
    for token in unknown:
        cleaned = cleaned.replace(token, "[unverified]")
    notes.append(
        f"{where}: removed unverified detail {unknown} — not present in the "
        f"evidence digest (anti-invention guard)."
    )
    return cleaned


def _clean_evidence_ids(value, valid_ids: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v in valid_ids][: _MAX_EVIDENCE]


def validate_explanation(payload: dict, digest: dict) -> tuple[dict, list[str]]:
    """Normalize + sanity-check an explanation payload against its digest."""
    notes: list[str] = []
    corpus = _corpus(digest)
    valid_ids = {item["id"] for item in digest.get("evidence") or []}
    p = payload if isinstance(payload, dict) else {}

    # ---- required top-level strings ---------------------------------------
    technical = _check_text(
        str(p.get("technical_summary") or "")[:_MAX_SUMMARY], corpus, notes, "technical_summary"
    )
    if not technical:
        technical = "No technical summary produced."
        notes.append("technical_summary missing — filled with placeholder.")

    # ---- root cause ----------------------------------------------------------
    rc = p.get("root_cause") if isinstance(p.get("root_cause"), dict) else {}
    rc_raw = str(rc.get("statement") or "")[:_MAX_CLAIM]
    rc_statement = _check_text(rc_raw, corpus, notes, "root_cause")
    rc_label = _label(rc.get("label"))
    rc_evidence = _clean_evidence_ids(rc.get("evidence_ids"), valid_ids)
    if rc_statement != rc_raw and rc_label in ("CONFIRMED", "PROBABLE"):
        # a claim that needed unverified detail removed can no longer be
        # presented as confirmed/probable
        notes.append(
            "root_cause contained unverified detail — label demoted to POSSIBLE."
        )
        rc_label = "POSSIBLE"
    if rc_statement and not rc_evidence and rc_label != "UNKNOWN":
        notes.append(
            "root_cause claimed without evidence references — degraded to UNKNOWN."
        )
        rc_label = "UNKNOWN"
    if not rc_statement:
        rc_statement = "No root-cause candidate exceeded UNKNOWN."
        rc_label = "UNKNOWN"
        notes.append("root_cause missing — filled with UNKNOWN.")
    root_cause = {
        "statement": rc_statement,
        "label": rc_label,
        "evidence_ids": rc_evidence,
        "basis": _check_text(str(rc.get("basis") or "")[:_MAX_CLAIM], corpus, notes, "root_cause.basis"),
    }

    # ---- confidence ----------------------------------------------------------
    conf = p.get("confidence") if isinstance(p.get("confidence"), dict) else {}
    confidence = {
        "label": _label(conf.get("label") or rc_label),
        "rationale": _check_text(
            str(conf.get("rationale") or "")[:_MAX_CLAIM], corpus, notes, "confidence.rationale"
        ),
    }

    # ---- lists of claims -------------------------------------------------------
    def claim_list(raw, where: str) -> list[dict]:
        out: list[dict] = []
        items = raw if isinstance(raw, list) else []
        for item in items[:_MAX_LIST]:
            if isinstance(item, str):
                out.append(
                    {
                        "statement": _check_text(item[:_MAX_CLAIM], corpus, notes, where),
                        "label": "POSSIBLE",
                        "evidence_ids": [],
                    }
                )
            elif isinstance(item, dict):
                statement = _check_text(str(item.get("statement") or "")[:_MAX_CLAIM], corpus, notes, where)
                if not statement:
                    continue
                evidence_ids = _clean_evidence_ids(item.get("evidence_ids"), valid_ids)
                label = _label(item.get("label"))
                if label == "CONFIRMED" and not evidence_ids:
                    label = "POSSIBLE"
                    notes.append(f"{where}: CONFIRMED claim without evidence demoted to POSSIBLE.")
                out.append(
                    {
                        "statement": statement,
                        "label": label,
                        "evidence_ids": evidence_ids,
                    }
                )
        return out

    possible_causes = claim_list(p.get("possible_causes"), "possible_causes")
    actions_raw = p.get("recommended_actions")
    recommended_actions = [
        _check_text(str(a)[:_MAX_CLAIM], corpus, notes, "recommended_actions")
        for a in (actions_raw if isinstance(actions_raw, list) else [])
        if a
        ][:_MAX_LIST]
    questions_raw = p.get("vendor_questions")
    vendor_questions = [
        _check_text(str(q)[:_MAX_CLAIM], corpus, notes, "vendor_questions")
        for q in (questions_raw if isinstance(questions_raw, list) else [])
        if q
        ][:_MAX_LIST]

    # ---- evidence used ---------------------------------------------------------
    used_ids: set[str] = set(rc_evidence)
    for c in possible_causes:
        used_ids.update(c["evidence_ids"])
    evidence_used = [
        {
            "id": item["id"],
            "file": item["file"],
            "file_id": item.get("file_id"),
            "line_number": item["line_number"],
            "raw_excerpt": item["raw_excerpt"],
        }
        for item in digest.get("evidence") or []
        if item["id"] in used_ids
    ][:_MAX_EVIDENCE]

    caveats_raw = p.get("caveats")
    caveats = [
        _check_text(str(c)[:_MAX_CLAIM], corpus, notes, "caveats")
        for c in (caveats_raw if isinstance(caveats_raw, list) else [])
        if c
        ][:_MAX_LIST]

    clean = {
        "technical_summary": technical,
        "root_cause": root_cause,
        "confidence": confidence,
        "possible_causes": possible_causes,
        "recommended_actions": recommended_actions,
        "vendor_questions": vendor_questions,
        "evidence": evidence_used,
        "caveats": caveats,
        "labels": {
            "vocabulary": list(LABELS),
            "legend": {
                "CONFIRMED": "multi-source log evidence directly supports the statement",
                "PROBABLE": "strong single/multi-source evidence; plausible alternatives remain",
                "POSSIBLE": "consistent with the evidence but unproven (hypothesis)",
                "UNKNOWN": "cannot be determined from the available evidence",
            },
        },
    }
    return clean, notes
