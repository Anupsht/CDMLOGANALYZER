# Technician Guide

Day-to-day workflow for field technicians and service desks.

## 1. Sign in

Open the dashboard, sign in with your account. Sessions expire after 8 h;
five wrong passwords lock the account for 15 minutes (contact an ADMIN to
reset sooner if needed).

## 2. Upload logs

**Logs → Upload**: select the ZIP (or `.txt/.log/.csv/.json`) from the
machine export, pick the machine model (P2600N / P2800N / P2600L) and the
machine. Rules of thumb:

* One upload per machine export bundle; re-uploading the same file is a
  no-op (checksum duplicate detection).
* Size limits: 200 MB per file, 1 GB uncompressed per ZIP, 500 files per ZIP.
* Archives with path traversal, executables or zip-bomb ratios are rejected
  automatically — if an export fails, re-export it on the machine.

Processing runs in the background; the log status goes
`UPLOADED → PARSING → … → COMPLETED/FAILED` (refresh to poll).

## 3. Read the results

* **Transactions** — every detected transaction with model, status, amount
  and timestamps. Open one for the timeline.
* **Timeline** — the correlated event flow (cash in → escrow → stored →
  host response → …), normalized across models.
* **Diagnostics tab** — the evidence-based assessment: classification,
  findings with `file · line · timestamp · raw text` evidence, confidence
  (LOW → VERY_HIGH) and hedged possible causes. A single error code is
  never a confirmed jam — the engine requires multi-source evidence.

## 4. AI explanation & vendor report

On a transaction → **Vendor Report** tab:

1. *Generate explanation* — a bounded, validated narrative over the
   deterministic results (labels: CONFIRMED / PROBABLE / POSSIBLE / UNKNOWN).
2. *Export PDF / Export Excel* — vendor escalation packages with full
   evidence traceability.

The AI layer only explains what the rules engine already found; it never
replaces deterministic analysis.

## 5. Cases

**Cases → Open a case** when a machine needs follow-up (repeat jams, sensor
abnormalities, escalated maintenance flags). Link the transaction reference
so reviewers can jump straight to the evidence. Supervisors close or review
cases; every transition is audited.

## 6. Machine health

**Machine Health** — per-machine scores, trends and maintenance flags
(WATCH / WARNING / HIGH_RISK). Flags are **triage hints derived from rate
increases** — they do not declare a component failed. Investigate flagged
machines first; confirm any hardware conclusion physically.

## 7. Troubleshooting quick answers

See the Troubleshooting Guide (`troubleshooting-guide.md`) for failed
uploads, "unknown model" exports, empty timelines and report errors.
