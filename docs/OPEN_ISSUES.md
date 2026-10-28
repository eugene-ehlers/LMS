# LMS Open Issues

Issues that are acceptable for dummy and test implementations but must be closed before production.

Each issue is classified as:
- **Decide later**: a rule or design choice that is not yet needed. Close when the case becomes real.
- **Rule change**: a locked decision must be updated before production.
- **Code change**: existing code must be updated before production.
- **Database change**: a schema or migration change is required before production.

Last updated: 2026-10-28

## Dummies (Agent A)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| D1 | Wire format for rate, term, and application number is not locked. Dummy uses integer basis points, term count plus frequency, and APP- plus eight digits. | Decide later | Lock the wire format when a real decision engine is integrated. Code and database already store the values; only the contract needs a lock. |
| D2 | Service address is returned only from the booking identity read. Organisation context does not return addresses. | Decide later | Confirm with Enigma whether organisation context should return addresses. No LMS change until Enigma exposes the field. |
| D3 | When the name or ID number on the application differs from the Enigma booking read, which value is frozen is not locked. | Decide later | Lock the rule when a real case arises. Dummy does not reconcile them. |

## Notifications (Agent D)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| N1 | Layer 1 has no read-only readiness method. The push reads already-issued statements. | Code change | Add a read-only method on Documents that returns whether a statement for a period has already been issued, without calling issue_statement. |
| N2 | Enigma has no consumer-registration operation that avoids contact details. Dummy answers until Enigma exposes one. | Decide later | Enigma must expose a registration check that does not return email or mobile. LMS code already fails closed. |
| N3 | "One month" between successive Day-1 statements has no day count or calendar boundary. | Rule change | Lock the calendar boundary (calendar month, or 30 days from previous statement) in Decision 12. |
| N4 | A stored statement has no section 21 classification and no pure-hosting flag. A blank NCR number fails closed. | Database change | Add a classification column (short_term, unsecured, pure_hosting, zero_cost, cpa_laybye) to the statement or agreement so the NCR exemption can be applied. |
| N5 | NCR character format, call-centre role name, Enigma page URLs, and machine action for the push are not locked. | Decide later | Lock each when the real Enigma and push provider are integrated. Current code fails closed on missing values. |

## Campaigns and elections (Agent B)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| C1 | Fall-away choice and trigger are stored on the campaign and also as an organisation election with a product override. The lock does not say which value applies when they differ. | Rule change | Add a sentence to Decision 3 or Decision 19 that names the precedence (campaign value wins, or organisation value wins). |
| C2 | The lock does not say which campaign applies when more than one period contains the recognition date. Intake stores nothing. | Rule change | Lock the rule (most recent campaign, or fail closed) in Decision 3. |
| C3 | The lock does not say whether a qualifying loan keeps the decision-engine rate or uses the campaign net. Both are stored. | Rule change | Lock the rule in Decision 3 or Decision 13. |
| C4 | Decision 8 names a residual default of R100. Decision 19 says an unset election fails closed and also names that default. A null threshold is left unset and resolve fails. | Rule change | Decide whether R100 is a platform default that fills when unset, or whether unset always fails closed. Update Decision 8 or Decision 19. |
| C5 | campaign_rate still rejects a discount above the base. | Code change | Update campaign_rate to floor the net at 0 % instead of rejecting the pair. |
| C6 | resolve_residual_threshold_cents still fills R50 (5 000 cents) when both levels are null. | Code change | Update the function to fail closed or to fill R100, depending on the resolution of C4. |

## Payment rails (Agent C)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| P1 | Section 19 does not name debit_orders_enabled as the section 4 automation switch. | Rule change | Add debit_orders_enabled to the elections in Decision 19. |
| P2 | Loan-number character pattern and stored contractual instalment are unset. The loan line reads the amount still outstanding on that due date. | Decide later | Lock the loan-number pattern when the real numbering scheme is finalised. The outstanding-amount approach is acceptable for testing. |
| P3 | Bankserv has no DebiCheck record type and no stated hash algorithm. Consumer homing account and 10-character abbreviated name are not LMS fields. A credit-life receipt has no insurer hand-off. | Decide later | Lock the Bankserv layout details and the insurer hand-off when the real rail and insurer contracts are in place. |
| P4 | Whether interest accruing on the due date is itself due that day is unsettled. The rail bills the whole unbilled memo through bill_interest. | Rule change | Lock whether interest accruing on the due date is due that day in Decision 1 or Decision 8. |

## Regulatory extracts (Agent E)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| R1 | Decision 21 says "micro" and "Laybye/BNPL". The ledger stores short_term, unsecured, zero_cost, and cpa_layby. pure_hosting is not a column. The map is not locked. A missing pure_hosting value fails closed when a row would require the number. | Rule change | Lock the classification map in Decision 21. Add pure_hosting as a column or as a value that the extract can read. |
| R2 | The ledger can post a full write-off journal. The Form 39 write-off cell stays empty. | Decide later | Lock whether Form 39 should include write-offs when the real Form 39 layout is confirmed. |

## Rate or fee change (Agent H)

`docs/LOCKED_DECISIONS.md` on this branch still ends at section 21. On `main` the file is a placeholder that points at `/tmp/locked_updated.md`, which is not present. The text followed here is the restored document through section 28 (commit `325acc6` on `cursor/restore-locked-decisions-ccde`). That file was not edited.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| H1 | Main's locked-decisions file is a placeholder. This branch's copy ends at section 21. | Rule change | Restore `docs/LOCKED_DECISIONS.md` from the section 28 text. Do not treat the placeholder as the rule. |
| H2 | Section 104(2) for a non-campaign change is not its own locked section. Decision 28 states the five-business-day sentence inside collection campaigns. The orchestration list had no rate-or-fee flow. | Rule change | Add a locked section for the non-campaign path, or say that Decision 28's notice sentence also covers it. |
| H3 | When the change ends, the original rate and fees resume. That is an increase relative to the reduced values. Section 104(1) prohibits a unilateral increase. The brief requires the resume. No second notice is taken. | Rule change | Lock whether the resume needs its own section 104(2) notice or an agreement. |
| H4 | Decision 11 option B says "issue the section 104 notice" and does not say subsection (2) or (3). Section 104(3) is a notice no later than 30 business days after a variable-rate change. | Rule change | Lock which subsection Decision 11 uses. This module does not implement section 104(3) or a repo-rate fall. |
| H5 | The brief does not say whether the end date is inside the new values. | Decide later | This code treats `end_date` as the last recognition date of the new values. The original rate and fees resume on the next recognition date. |
| H6 | "Time of payment" has no locked wire format. Section 104(2)(c) is the frequency or time for payment of a credit fee or charge. | Decide later | This code stores `fee_payment_time` as a Johannesburg date and `fee_payment_frequency` as a locked frequency. It does not write the loan's `payment_frequency`. The whole overlay, including frequency and payment time, stops after the end date. |
| H7 | The role `lms.rate_fee_change.write` is not named in Decision 19. | Decide later | Lock the role name. Enigma grants it. The LMS does not store it. |
| H8 | The ledger does not store contractual fee amounts or a product code. | Decide later | Original fees are taken from the apply request. A product selector fails closed (`product-unsupported`). |
| H9 | Presidential one-off holidays are not inside `add_business_days`. | Decide later | The service accepts `extra_holidays`. The HTTP route does not. |
| H10 | A statement does not build a new fee schedule. | Decide later | If a payment-time overlay does not include the statement's due date, the statement levy fails closed (`payment-time`). |
| H11 | The brief does not say to restate posted accruals. | Decide later | An apply or an end that would cover a day already accrued or levied fails closed (`accrual-already-posted` or `fee-already-levied`). |
| H12 | Decision 3 fall-away is the origination discount. This overlay is not passed through that flag. | Rule change | Lock whether a non-campaign reduction falls away on default. This code ends it only on the end date. |
| H13 | A timestamp without a zone cannot be sealed. Decision 1 requires the zone so the Johannesburg day is known. | Decide later | The failure is returned and is not written. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 17 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 12 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 3 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

The counts include the Agent H rows above. The earlier rows are unchanged.
