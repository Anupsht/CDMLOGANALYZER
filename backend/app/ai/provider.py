"""Explanation providers (Phase 8, spec §1–§3).

Two implementations of the same contract:

* :class:`DeterministicComposer` — the default. Composes the explanation
  strictly from the digest (which itself is the output of the deterministic
  rules engine). No network, no model — nothing can be invented.
* :class:`ExternalLLMProvider` — used only when ``CDM_AI_BASE_URL`` and
  ``CDM_AI_API_KEY`` are configured. Sends the *structured digest* (never
  raw log files) to an OpenAI-compatible chat-completions endpoint with a
  strict safety prompt, and parses a JSON reply. Its output still passes
  :mod:`app.ai.safety` validation; any failure falls back to the composer.

The deterministic composer is the honest fallback: its output is labelled
as machine-composed, never as an LLM opinion.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.ai.safety import epistemic_from_confidence
from app.core.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a maintenance-analysis assistant for GRG CDM cash
dispenser logs. You receive a structured JSON digest of ONE transaction:
normalized events, cash states, host events, hardware events, deterministic
rule results, ranked root-cause candidates and evidence items (EV-xxx ids).

Hard rules:
- Use ONLY the labels CONFIRMED, PROBABLE, POSSIBLE, UNKNOWN.
- Never invent events, sensor states, cash states, host responses, error
  meanings, serial numbers or denominations. Every factual claim must cite
  evidence_ids that exist in the digest.
- Error codes have NO meaning beyond what the digest states; if the digest
  says "interpretation pending vendor table", the meaning is UNKNOWN.
- Root causes are hypotheses unless labelled CONFIRMED by multi-source
  evidence; name behaviours, never definitive component failures.
- Confidence expresses evidence strength, never certainty.

Reply with ONLY a JSON object:
{
  "technical_summary": string,
  "root_cause": {"statement": string, "label": "CONFIRMED|PROBABLE|POSSIBLE|UNKNOWN",
                 "evidence_ids": ["EV-..."], "basis": string},
  "confidence": {"label": "...", "rationale": string},
  "possible_causes": [{"statement": string, "label": "...", "evidence_ids": [...]}],
  "recommended_actions": [string],
  "vendor_questions": [string],
  "caveats": [string]
}
"""


class DeterministicComposer:
    """Composes the explanation from the digest without any model."""

    name = "deterministic-rules-composer"
    generator = "deterministic"

    def explain(self, digest: dict) -> dict:
        txn = digest.get("transaction") or {}
        machine = digest.get("machine") or {}
        engine = digest.get("engine_report") or {}
        candidates = digest.get("root_cause_candidates") or []
        rules = digest.get("rule_results") or []
        hw = digest.get("hardware_events") or {}
        cash = digest.get("cash_states") or {}

        # ---- technical summary (facts only) --------------------------------
        stage_note = ""
        confirmed = txn.get("stages_confirmed") or []
        not_confirmed = txn.get("stages_not_confirmed") or []
        if confirmed:
            stage_note = (
                f" Lifecycle stages with confirming events: {', '.join(confirmed)}"
                + (f"; not confirmed: {', '.join(not_confirmed)}." if not_confirmed else ".")
            )
        amount = txn.get("amount")
        amount_txt = f"{amount:.2f} {txn.get('currency') or ''}".strip() if amount is not None else "unknown amount"
        technical_summary = (
            f"Transaction {txn.get('transaction_id')} on {txn.get('model_code') or 'unknown model'} "
            f"(machine {machine.get('serial_number') or 'unbound'}) started "
            f"{txn.get('start_time') or 'unknown'} and ended {txn.get('end_time') or 'unknown'} "
            f"with final status {txn.get('status')} and {amount_txt}. "
            f"Final cash state: {cash.get('final_cash_state') or 'UNKNOWN'}.{stage_note} "
            f"{engine.get('summary') or ''}"
        ).strip()

        # ---- root cause ------------------------------------------------------
        if candidates:
            top = candidates[0]
            label = top.get("epistemic_label", "UNKNOWN")
            statement = f"{top['candidate']}: {top['statement']}"
            if label != "CONFIRMED":
                statement += " (hypothesis — not a component-level root cause)"
            root_cause = {
                "statement": statement,
                "label": label,
                "evidence_ids": top.get("evidence_ids") or [],
                "basis": (
                    f"Top-ranked deterministic rule result ({top.get('confidence')} evidence "
                    f"strength, class {top.get('diagnosis_class')})."
                ),
            }
            confidence = {
                "label": label,
                "rationale": (
                    f"Rule '{top['candidate']}' evaluated at {top.get('confidence')} evidence "
                    f"strength on {len(top.get('evidence_ids') or [])} evidence reference(s). "
                    f"Labels express evidence strength, not certainty."
                ),
            }
        else:
            root_cause = {
                "statement": "No failure-indicating rule triggered; transaction matches NORMAL_COMPLETION.",
                "label": "CONFIRMED" if engine.get("classification") == "NORMAL_COMPLETION" else "UNKNOWN",
                "evidence_ids": [],
                "basis": "Deterministic rules found no failure indicators.",
            }
            confidence = {
                "label": "CONFIRMED" if engine.get("classification") == "NORMAL_COMPLETION" else "UNKNOWN",
                "rationale": "Derived directly from the deterministic rules-engine classification.",
            }

        # ---- possible causes (hypotheses from the rules) ----------------------
        possible_causes: list[dict] = []
        for rule in rules:
            if rule["rule_id"] == "NORMAL_COMPLETION":
                continue
            ev_ids = rule.get("evidence_ids") or []
            for cause in rule.get("possible_causes") or []:
                text = cause if isinstance(cause, str) else json.dumps(cause, default=str)
                possible_causes.append(
                    {
                        "statement": f"{rule['rule_id']}: {text}",
                        "label": "POSSIBLE",
                        "evidence_ids": ev_ids,
                    }
                )
        possible_causes = possible_causes[:8]

        # ---- recommended actions -------------------------------------------------
        actions = [
            rule["recommended_action"]
            for rule in rules
            if rule.get("recommended_action") and rule["rule_id"] != "NORMAL_COMPLETION"
        ]
        if not actions:
            actions = [
                "No rule-specific action configured for the triggered rules — review the "
                "evidence and the vendor questions below."
                if root_cause["label"] != "CONFIRMED" or candidates
                else "No action required; the deterministic rules found no failure indicators."
            ]

        # ---- vendor questions (questions only — never assertions) -----------------
        questions = self._vendor_questions(digest)

        caveats = [
            "Explanation composed deterministically from the rules-engine results — "
            "no external AI model was used (set CDM_AI_BASE_URL to enable one).",
            "Statements never invent events, sensor states, cash states, host responses, "
            "error meanings, serial numbers or denominations; every fact traces to an "
            "evidence identifier.",
            "Error-code meanings are only as stated in the model catalogue; codes marked "
            "'interpretation pending vendor table' remain UNKNOWN.",
        ]

        return {
            "technical_summary": technical_summary,
            "root_cause": root_cause,
            "confidence": confidence,
            "possible_causes": possible_causes,
            "recommended_actions": actions[:8],
            "vendor_questions": questions,
            "caveats": caveats,
        }

    def _vendor_questions(self, digest: dict) -> list[str]:
        model = (digest.get("transaction") or {}).get("model_code") or "this model"
        questions: list[str] = []
        machine_serial = (digest.get("machine") or {}).get("serial_number")

        # unknown-meaning error codes → ask for the official table
        codes = [
            e.get("error_code")
            for e in digest.get("error_events") or []
            if e.get("error_code")
        ]
        pending = [
            e["error_code"]
            for e in digest.get("error_events") or []
            if e.get("error_code")
            and "pending vendor table" in (e.get("error_description") or "")
        ]
        if pending:
            seen = list(dict.fromkeys(pending))[:4]
            questions.append(
                f"Please provide the official {model} error-code table covering {', '.join(seen)} "
                f"(captured verbatim; meaning is pending vendor confirmation)."
            )
        elif codes:
            seen = list(dict.fromkeys(codes))[:4]
            questions.append(
                f"Please confirm the meaning and expected handling of error code(s) "
                f"{', '.join(seen)} as reported by {model}."
            )

        # motor timeouts → ask for the official timing envelope
        for m in (digest.get("hardware_events") or {}).get("motors") or []:
            if m.get("timed_out"):
                questions.append(
                    f"Please confirm the expected maximum runtime for motor '{m.get('motor')}' "
                    f"on {model}"
                    + (f" (log shows a {m.get('timeout_ms')} ms timeout at EV evidence)." if m.get("timeout_ms") else ".")
                )

        # faults → ask for the official service procedure
        for f in (digest.get("hardware_events") or {}).get("faults") or []:
            subject = f"{f.get('subject_kind') or ''} {f.get('subject_name') or ''}".strip() or "the affected unit"
            questions.append(
                f"For a '{f.get('classification')}' assessment on {subject} of {model}, "
                f"please advise the recommended vendor service procedure."
            )

        # host vs final outcome mismatch
        txn = digest.get("transaction") or {}
        host_events = digest.get("host_events") or []
        declined = any(e.get("event") == "HOST_DECLINED" for e in host_events)
        if declined and txn.get("status") not in ("DECLINED",):
            questions.append(
                f"Transaction {txn.get('transaction_id')} received a host decline but ended with "
                f"status {txn.get('status')}. Please confirm the expected end-to-end behaviour "
                f"for this scenario on {model}."
            )

        if machine_serial:
            questions.append(
                f"Please confirm the service history and firmware level for machine {machine_serial}."
            )

        return questions[:6]


class ExternalLLMProvider:
    """OpenAI-compatible chat-completions client (explanation layer only)."""

    name = "openai-compatible-llm"
    generator = "external-llm"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def explain(self, digest: dict) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Digest:\n" + json.dumps(digest, default=str),
                },
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            body = json.load(resp)
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM reply is not a JSON object")
        return parsed


def get_provider():
    """Return the configured provider (external LLM if configured, else composer)."""
    settings = get_settings()
    if settings.ai_base_url and settings.ai_api_key:
        return ExternalLLMProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model or "gpt-4o-mini",
            timeout=settings.ai_timeout_seconds,
        )
    return DeterministicComposer()
