# AI explanations & vendor reporting (Phase 8)

The deterministic engines (Phases 2–5) remain the **only** source of truth.
Phase 8 adds an *explanation layer* on top of them, plus vendor-escalation
reporting (PDF / Excel), all fully evidence-referenced.

```
deterministic analysis            structured digest            provider
(rules, hardware, findings)  →    (app/ai/digest.py)      →    deterministic composer
                                                              or external LLM (*)
                                                         →    safety validation
                                                              (app/ai/safety.py)
                                                         →    stored explanation
                                                              (ai_explanations)
                                                         →    vendor report → PDF / XLSX
```

(*) Only when `CDM_AI_BASE_URL` + `CDM_AI_API_KEY` are configured
(OpenAI-compatible chat-completions). Otherwise the explanation is composed
deterministically from the rule results and labelled as such — no model, no
network, nothing invented.

## 1. AI input (spec §1)

`GET /api/transactions/{txn_id}/ai-digest` builds the exact payload any
provider receives — one transaction, **structured and bounded**, never raw
log files:

transaction summary · normalized events · cash states · host events ·
hardware events (sensors/motors/gates/transports/faults) · rule results ·
ranked root-cause candidates · evidence (`EV-001…` = file + line + ≤240-char
verbatim excerpt). Bounds: 300 events, 200 evidence items; the digest
records its own truncation flags and a `digest_sha256`.

## 2. AI output (spec §2)

`POST /api/transactions/{txn_id}/ai-explanation` → validated payload:

technical summary · root cause (statement + label + evidence ids + basis) ·
confidence (label + rationale) · possible causes · recommended actions ·
vendor questions · the evidence subset used · caveats · label legend.

Every generation is persisted (`ai_explanations` table: provider, digest
hash, payload, safety notes) so review and vendor reports reference a
stable artifact. `GET …/ai-explanation` returns the latest one.

## 3. AI safety (spec §3)

`app/ai/safety.py` — every explanation passes `validate_explanation`:

* Epistemic vocabulary is exactly **CONFIRMED / PROBABLE / POSSIBLE /
  UNKNOWN** (aliases like "CERTAIN" are normalized; unknown words degrade
  to UNKNOWN). Rules-engine confidence maps VERY_HIGH→CONFIRMED,
  HIGH→PROBABLE, MODERATE→POSSIBLE, LOW→UNKNOWN.
* Claims may only cite evidence ids that exist in the digest; a CONFIRMED
  claim without surviving evidence is demoted (CONFIRMED→POSSIBLE with any
  real evidence ref, else UNKNOWN).
* **Anti-invention guard:** code-like tokens and serial/denomination/
  amount-like numbers in any claim must appear in the digest corpus —
  anything else is replaced with `[unverified]` and recorded in
  `safety_notes`. A root cause whose text needed redaction is demoted from
  CONFIRMED/PROBABLE to POSSIBLE.
* The external-LLM system prompt embeds the same contract (never invent
  events, sensor states, cash states, host responses, error meanings,
  serial numbers, denominations; error codes mean only what the model
  catalogue says).

## 4–6. Vendor report, PDF, Excel

* `GET /api/transactions/{txn_id}/vendor-report` — machine, model,
  location, transaction, timestamps, amount, problem, timeline, errors,
  hardware state, cash state, host state, analysis (engine + AI), evidence,
  vendor questions. Generates the explanation first if none exists.
* `GET /api/transactions/{txn_id}/report.pdf` — professional A4 PDF
  (reportlab): header band, incident summary, timeline, cash trace,
  hardware events, analysis, recommendations, vendor questions, evidence
  appendix, page footers.
* `GET /api/transactions/{txn_id}/report.xlsx` — openpyxl workbook with the
  six required sheets: Transaction Summary, Events, Cash Trace, Hardware
  Events, Errors, Analysis (auto-filter, frozen headers).

## 7. Traceability

Every conclusion — rule finding, fault statement, timeline row, AI claim —
carries `file:line (EV-xxx)` references resolvable in the evidence appendix
and clickable in the UI (deep links into the log viewer). The report's
`traceability` block records the digest hash, provider and evidence count.

## 8. Completion flow (UI)

Transaction Details → **Vendor Report** section:
**Generate explanation** (or Regenerate) → review claims/labels/evidence →
**Export PDF** → **Export Excel**. The deterministic analysis is never
replaced — the section shows engine findings and the explanation side by
side.
