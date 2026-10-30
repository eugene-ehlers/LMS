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
| N6 | Orchestration section 6 calls Notifications.push after Documents.issue_statement when the consumer is registered. This tree has no notifications module, and issue_statement does not push. | Code change | Bring the statement-ready push onto this tree and call it after a statement is issued. The push carries no collection content. |

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

## Merged smoke

These rows are the contradictions the seven-path smoke produced. S1 was closed by the early-settlement path. S2 is closed. S3 remains.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| S3 | The 1 May interest memo after the R219 receipt was 3.1451612903 rands, on the R1 950 left after the receipt. Sections 1 and 8 treat the day as 00:00 and capitalise before allocating. The receipt path posted before the statement accrued that day. A memo on the R2 000 balance at the start of the day would be 3.2258064516 rands. The memo was not billed. | Rule change | Say which flow wins when a receipt and that day's accrual share a recognition date. |

S1 is closed. `Ledger.quote_settlement` delegates to the calculation engine. `Documents.settlement_quote` calls that method. There is still one quote formula.

## Early settlement (Agent F)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| F1 | The five-business-day quote window is orchestration section 7 and section 113 (`binding_until`). It is not a numbered paragraph in the locked decisions. | Decide later | Add the window to the locked decisions when that text is next revised. Do not treat this row as a new lock. |
| F2 | Decision 1 does not say whether interest inside the five-day window runs to the quote as-of date or to a later receipt date. This path keeps the quoted as-of amount and does not accrue the days in between. | Rule change | Say which date is the settlement date for interest. |
| F3 | A receipt above the quote has no locked home on this path. Decision 4 sends an ordinary surplus to Laybye and consolidates when the Laybye covers the settlement balance. That consolidation is not this receipt. The surplus is refused and not allocated. | Decide later | Lock where a settlement surplus goes, or confirm that only an exact match is a settlement. |
| F4 | The calculation engine closes an open in-duplum episode when it settles. This path does not. Decision 7 depends on the trigger, and a settlement is not named as a close. | Rule change | Say whether settlement closes an open episode. |
| F5 | `Documents.settlement_quote` does not take repo rows. The quote route rejects a non-empty repo list. An unsecured execute can still accrue with repos, then fail closed when that accrual does not match the quote. | Code change | Give the quote the same repo rows the accrual uses, or reject repos on execute as well. |
| F6 | A naive recognition timestamp, and an unknown agreement id, are returned as failures and are not written to the audit log. The log needs an organisation and an aware timestamp. | Code change | Seal those two failures once there is a defined actor and an aware timestamp to attach. |
| F7 | The calculation engine rounds each interest bill and clears the unbilled remainder. The ledger rounds the cumulative memo. On 1 March to 10 April 2026 the two totals matched (6 667 cents). A one-cent difference fails closed. No balancing journal is posted. | Code change | Use one rounding rule for both books, or record that a one-cent difference stays a refusal. |

## Closed

| ID | Resolution |
|----|------------|
| C4 | Decision 19. The residual write-off threshold has a platform default of R100. An unset organisation value and an unset product value fill R100. A stored value, including zero, is kept. A product value overrides the organisation. |
| C6 | `resolve_residual_threshold_cents` fills 10 000 cents when both levels are null. |
| C7 | Decision 19. Booking fails closed when the in-duplum trigger is unset on both the organisation and the product. |
| S2 | Decision 2. The settlement quote uses the booked initiation fee. A capitalised fee is already part of the loan value and is not added again. A fee that is not capitalised has its outstanding portion added. VAT is included. The client remains accountable for the VAT portion. |
| H2 | Section 29. A non-campaign rate or fee change requires a written notice of at least five business days before it takes effect (section 104(2)). |
| H3 | Section 29. A temporary reduction is stored as a concession or discount that goes to zero when the period ends. The original contractual rate and fees remain effective. Resuming the original rate does not require a second notice. An interest-rate change does not automatically reduce the contractual instalment. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 10 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 10 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 6 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

The merged smoke added C7, N6, S1, S2, and S3. Early settlement closed S1. C4, C6, C7, S2, H2, and H3 are closed. S3 remains. F1 to F7 are the gaps the early-settlement path raised. Booking refuses a missing in-duplum trigger. An unset residual threshold fills R100. The settlement quote uses the booked initiation fee, and VAT on that fee is part of the amount owing.
