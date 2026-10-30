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
| C4 | Decision 8 names a residual default of R100. Decision 19 says an unset election fails closed and also names that default. A null threshold is left unset and resolve fails. | Rule change | Closed. Decision 19: the platform default is R100. An unset organisation or product value fills R100. |
| C5 | campaign_rate still rejects a discount above the base. | Code change | Update campaign_rate to floor the net at 0 % instead of rejecting the pair. |
| C6 | resolve_residual_threshold_cents still fills R50 (5 000 cents) when both levels are null. | Code change | Closed. The function fills R100 (10 000 cents) when both levels are null. |

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

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 9 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 7 | Update docs/LOCKED_DECISIONS.md. |
| Code change | 3 | Update the existing functions. |
| Database change | 1 | Add a classification column. |

All agents have completed. All issues are recorded so they can be closed in a single pass before production.

The counts above were written before the staff screens. The rows below are additional.

## Staff UI (Agent K)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| K1 | No route records the daily calculation batch. The batch screen calls `GET /v1/staff/organisations/{id}/audit` and reports that no batch run is stored. It does not accrue, capitalise, or flag default. | Code change | A batch module must record start, finish, accounts processed, accounts failed, and a reason per failure before the screen can show a run. |
| K2 | `lms.collection_campaigns.api.dispatch` has no list or read route. The list and the edit form read `CollectionCampaigns.campaigns` for the signed-in organisation. They do not apply overlap, notice, or rate rules. | Code change | Add a read to the collection-campaign route. The screen should call that route. |
| K3 | A missing `lms.collection_campaign.write` is mapped by `authorise` to an ambiguous Enigma failure, which names the wrong cause. The screen states the missing role and does not call the route in that case. Timeout and a suspended enrolment still go to the route. | Code change | `authorise` should return the missing-role reason. The screen can then call the route for that case as well. |
| K4 | `STAFF_UI_REPORTED` is not in `ref_audit_event_type`. The in-process audit log accepts it. A database insert would fail. `CAMPAIGN_CREATED` and the other Layer 2 event types are in the same position. | Database change | Add the event codes before those rows are inserted. |
| K5 | The collection-campaign branch still names its migration `0008_collection_campaigns.sql`. This branch names it `0009_collection_campaigns.sql` so it does not share 0008 with `0008_layer2_staff.sql`. | Database change | Keep 0009 when the collection-campaign branch is merged. Do not restore the 0008 filename beside the staff migration. |
| K6 | `docs/LOCKED_DECISIONS.md` on `main` is a stub. This branch keeps Layer 2 sections 1 to 27 and appends section 28 from the collection-campaign branch. The collection branch's section 21 was not copied: it omits the compulsory NCR number and the all-zeros test number. | Rule change | Land one locked file that contains sections 1 to 28. Do not treat the stub on `main` as the rule text. |
| K7 | Decision 3 on this file says every campaign has an end date. Section 28 allows an open-ended collection campaign. The existing collection-campaign route accepts a null end date. The screen sends null when the field is blank and shows the route's result. | Rule change | Name which sentence applies to a collection campaign. The screen does not choose. |
| K8 | The audit extract accepts the Layer 2 write roles and does not accept `lms.collection_campaign.write` on its own. No batch-status role is locked. | Decide later | An operator who holds only the collection-campaign role cannot open the batch screen. Lock a role if that operator must see batch status. |
| K9 | A blank NCR number is refused by the staff route as `ncr_registration_number is required` before the service sentence that says the number is compulsory. A number of all zeros, including `0000000` and `NCRCP0000`, is accepted by that route. | Decide later | The screen shows the route's reason. The two refusal sentences name the same blank field. |

## Closed

C4 and C6 are marked closed in the campaigns table above. C7, S2, H2, and H3 were recorded on other branches. They are closed here by the same locks.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| C7 | Decision 19 says an unset in-duplum trigger fails closed. Servicing.book stores None and returns the agreement. Collections.bind then fails with trigger-unset. | Rule change | Closed. Decision 19: booking fails closed if the in-duplum trigger is unset. |
| S2 | A settlement quote on 15 May 2026 included initiation of 30 475 cents. The agreement was booked with an initiation fee of 0 cents. The quote builds an engine agreement without that booked amount, and the engine prices the statutory formula. The fee was not posted. | Code change | Closed. Decision 2: the quote uses the booked initiation fee. A capitalised fee is not added again. An uncapitalised outstanding portion is added. VAT is included. |
| H2 | Section 104(2) for a non-campaign change is not its own locked section. Decision 28 states the five-business-day sentence inside collection campaigns. The orchestration list had no rate-or-fee flow. | Rule change | Closed. Decision 11: a non-campaign rate or fee change also requires a written notice of at least five business days before it takes effect (section 104(2)). |
| H3 | When the change ends, the original rate and fees resume. That is an increase relative to the reduced values. Section 104(1) prohibits a unilateral increase. The brief requires the resume. No second notice is taken. | Rule change | Closed. Decision 29: the reduction is a concession or discount that goes to zero when the period ends. The original rate and fees are not changed. Resuming does not require a second notice. The contractual instalment stays stable unless a reduced-payment process is followed. |
