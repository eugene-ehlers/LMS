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
| N6 | Orchestration section 6 calls Notifications.push after Documents.issue_statement when the consumer is registered. This tree has no notifications module, and issue_statement does not push. | Code change | Bring the statement-ready push onto this tree and call it after a statement is issued. The push carries no collection content. |

## Campaigns and elections (Agent B)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| C1 | Fall-away choice and trigger are stored on the campaign and also as an organisation election with a product override. The lock does not say which value applies when they differ. | Rule change | Add a sentence to Decision 3 or Decision 19 that names the precedence (campaign value wins, or organisation value wins). |
| C2 | The lock does not say which campaign applies when more than one period contains the recognition date. Intake stores nothing. | Rule change | Lock the rule (most recent campaign, or fail closed) in Decision 3. |
| C3 | The lock does not say whether a qualifying loan keeps the decision-engine rate or uses the campaign net. Both are stored. | Rule change | Lock the rule in Decision 3 or Decision 13. |
| C4 | Decision 8 names a residual default of R100. Decision 19 says an unset election fails closed and also names that default. A null threshold is left unset and resolve fails. | Rule change | Decide whether R100 is a platform default that fills when unset, or whether unset always fails closed. Update Decision 8 or Decision 19. |
| C5 | campaign_rate still rejects a discount above the base. | Code change | Update campaign_rate to floor the net at 0 % instead of rejecting the pair. |
| C6 | resolve_residual_threshold_cents still fills R50 (5 000 cents) when both levels are null. | Code change | Update the function to fail closed or to fill R100, depending on the resolution of C4. |
| C7 | Decision 19 says an unset in-duplum trigger fails closed. Servicing.book stores None and returns the agreement. Collections.bind then fails with trigger-unset. | Rule change | Say whether booking itself must reject a missing trigger, or only a collections call that uses it. |

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

## Merged smoke

These rows are the contradictions the seven-path smoke produced. C4 and C6 were hit again and are not repeated here. Existing rows were not closed.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| S1 | Orchestration section 7 calls Ledger.quote_settlement, then Documents.settlement_quote. Ledger has no quote_settlement. Documents.settlement_quote calls the calculation engine and does not post. | Code change | Add the ledger method the flow names, or correct section 7 so it names the calculation engine. Do not add a second quote formula. |
| S2 | A settlement quote on 15 May 2026 included initiation of 30 475 cents. The agreement was booked with an initiation fee of 0 cents. The quote builds an engine agreement without that booked amount, and the engine prices the statutory initiation formula. The fee was not posted. | Code change | Pass the booked initiation amount into the quote, or record that a booked zero still means the statutory formula. |
| S3 | The 1 May interest memo after the R219 receipt was 3.1451612903 rands, on the R1 950 left after the receipt. Sections 1 and 8 treat the day as 00:00 and capitalise before allocating. The receipt path posted before the statement accrued that day. A memo on the R2 000 balance at the start of the day would be 3.2258064516 rands. The memo was not billed. | Rule change | Say which flow wins when a receipt and that day's accrual share a recognition date. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 8 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 10 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 6 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

The merged smoke added C7, N6, S1, S2, and S3. It did not close any existing row.
