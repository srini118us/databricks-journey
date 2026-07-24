# Use Case 9 — SAP Journal-Risk ML + Output Governance

**Purpose.** Add a third specialist — a journal-entry anomaly detector — and the
output-guardrail layer that enforces the system's "honesty contract" (never call a
statistical anomaly "confirmed fraud").

## Files

- `journal_risk_gold_and_tools.ipynb` — trains a scikit-learn **IsolationForest**
  (n_estimators=100, contamination=0.05) on 50k journal-entry rows from
  `bdc_share_journal_entry`, flags anomalies, writes `workspace.default.gold_journal_risk`
  (weekend / manual / negative flags + a data-confidence guard at < 100 entries),
  and creates UC functions `get_journal_risk(company_code)` and
  `rank_journal_risk(min_entries)` for the Journal-Risk-Analyst.
- `output_guardrails.ipynb` — a hand-built two-layer output guardrail (managed AI
  Gateway is gated on the trial): Layer 1 regex PII/sensitive-data checks; Layer 2
  a business "honesty contract" that blocks "confirmed fraud" assertions and
  requires statistical / for-review framing on anomaly answers. Includes a
  `guardrail()` gate, demo cases, a 4-case eval, and an optional
  `guardrail_eval_results` Delta sink.

## Outputs

- Table `gold_journal_risk`; UC functions `get_journal_risk`, `rank_journal_risk`;
  a reusable output-guardrail function and its eval.

## Why it matters

An anomaly model that says "fraud" confidently is worse than useless. The guardrail
makes honesty a property enforced at the output boundary, not a matter of prompt
wording — the same philosophy as the data-confidence guard in Use Case 8.
