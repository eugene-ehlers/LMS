# LMS Open Issues

Issues that are acceptable for dummy and test implementations but must be closed before production.

Each issue is classified as:
- **Decide later**: a rule or design choice that is not yet needed. Close when the case becomes real.
- **Rule change**: a locked decision must be updated before production.
- **Code change**: existing code must be updated before production.
- **Database change**: a schema or migration change is required before production.

Last updated: 2026-10-30

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
| C5 | campaign_rate still rejects a discount above the base. | Code change | Update campaign_rate to floor the net at 0 % instead of rejecting the pair. |

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

`docs/LOCKED_DECISIONS.md` on this branch now ends at section 22. On `main` the file is a placeholder that points at `/tmp/locked_updated.md`, which is not present. Section 28 collection-campaign text is not on this branch. H1 records that.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| H1 | Main's locked-decisions file is a placeholder. This branch's copy ends at section 22. It does not include the section 28 collection-campaign text. | Rule change | Restore the section 28 text if that campaign lock is required on this branch. Do not treat the placeholder on main as the rule. |
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

## Closed

| ID | Resolution |
| --- | --- |
| C4 | Closed. Decision 19: the residual write-off threshold has a platform default of R100. An unset organisation or product value fills R100. Decision 8 names that same default. |
| C6 | Closed. `resolve_residual_threshold_cents` fills 10 000 cents when both levels are null. Zero remains a stored choice. |
| C7 | Closed. Decision 19: booking fails closed if the in-duplum trigger is unset. `Servicing.book` and `Ledger.book` refuse a missing trigger. |
| S2 | Closed. The settlement quote uses the booked initiation fee. A capitalised fee is already in the loan value and is not added again. A fee that is not capitalised is added, including the outstanding portion that is not yet due. VAT is included. The client remains accountable for the VAT portion. |
| H2 | Closed. Decision 22: a non-campaign rate or fee change also requires a written notice of at least five business days before it takes effect (section 104(2)). |
| H3 | Closed. Decision 22: a temporary reduction is a concession or discount that goes to zero when the period ends. The original contractual rate and fees remain effective. Resuming the original rate does not require a second notice. An interest-rate change does not reduce the contractual instalment. |

## Summary

| Classification | Count | Action before production |
| --- | --- | --- |
| Decide later | 16 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 10 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 2 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

The counts are the open rows above. C4, C6, C7, S2, H2, and H3 are closed.
