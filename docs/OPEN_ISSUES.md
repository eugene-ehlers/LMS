# LMS Open Issues

Issues that are acceptable for dummy and test implementations but must be closed before production.

Each issue is classified as:
- **Decide later**: a rule or design choice that is not yet needed. Close when the case becomes real.
- **Rule change**: a locked decision must be updated before production.
- **Code change**: existing code must be updated before production.
- **Database change**: a schema or migration change is required before production.

Last updated: 2026-10-31

## Dummies (Agent A)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| D1 | Wire format for rate, term, and application number is not locked. Dummy uses integer basis points, term count plus frequency, and APP- plus eight digits. | Decide later | Lock the wire format when a real decision engine is integrated. Code and database already store the values; only the contract needs a lock. |
| D2 | Service address is returned only from the booking identity read. Organisation context does not return addresses. | Decide later | Confirm with Enigma whether organisation context should return addresses. No LMS change until Enigma exposes the field. |
| D3 | When the name or ID number on the application differs from the Enigma booking read, which value is frozen is not locked. | Decide later | Lock the rule when a real case arises. Dummy does not reconcile them. |

## Notifications (Agent D)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
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

## Payment rails (Agent C)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| P1 | Section 19 does not name debit_orders_enabled as the section 4 automation switch. | Rule change | Add debit_orders_enabled to the elections in Decision 19. |
| P2 | Loan-number character pattern and stored contractual instalment are unset. The loan line reads the amount still outstanding on that due date. | Decide later | Lock the loan-number pattern when the real numbering scheme is finalised. The outstanding-amount approach is acceptable for testing. |
| P3 | Bankserv has no DebiCheck record type and no stated hash algorithm. Consumer homing account and 10-character abbreviated name are not LMS fields. A credit-life receipt has no insurer hand-off. | Decide later | Lock the Bankserv layout details and the insurer hand-off when the real rail and insurer contracts are in place. |

## Regulatory extracts (Agent E)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| R1 | Decision 21 says "micro" and "Laybye/BNPL". The ledger stores short_term, unsecured, zero_cost, and cpa_layby. pure_hosting is not a column. The map is not locked. A missing pure_hosting value fails closed when a row would require the number. | Rule change | Lock the classification map in Decision 21. Add pure_hosting as a column or as a value that the extract can read. |
| R2 | The ledger can post a full write-off journal. The Form 39 write-off cell stays empty. | Decide later | Lock whether Form 39 should include write-offs when the real Form 39 layout is confirmed. |

## Collection-process removal

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| S3 | Decision 8 says promise-to-pay adherence and contactability are calculated on LMS data in reporting. Decision 23 lists promise-to-pay and contact as audited LMS changes. The collections split says the LMS does not store them. After this removal there is no LMS store for reporting to read. | Rule change | Update Decision 8 and Decision 23 so reporting and audit of those facts are attributed to the collections system. Do not add an LMS store to satisfy the old wording. |

## Merged smoke

These rows are the contradictions the seven-path smoke produced. S1 was closed by the early-settlement path. S2 is closed. S3 is closed by the existing Decision 1 order: capitalise due amounts, then allocate. The 1 May memo is on the morning balance. No new lock sentence was added.

## Daily batch status (Agent J)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| J2 | Decision 1 says the day starts at 00:00 and does not name a time zone. | Rule change | Lock Africa/Johannesburg on Decision 1, or name a different zone. This batch uses Africa/Johannesburg because the batch requirement states it. The stored offset is +02:00. |
| J4 | The morning default check has no locked module name. | Decide later | Name the module. This batch calls `default_check`. It does not call Collections.observe, which section 3 uses when a collections default is flagged. |
| J5 | "If the batch does not complete" does not say whether account failures on a finished batch block the next recognition date. | Rule change | Lock the gate. Until then: a finished batch has completed; account failures are stored, audited as `failed`, and shown as the last failed run; they do not raise the did-not-complete alert and do not block the next date. Only an unfinished run blocks, until a later finish of that same date or an explicit skip. |
| J6 | A retry after an incomplete or skipped run calls accrue, capitalise, and default check again for every account. | Rule change | Lock idempotency. A crash after some accounts were calculated can calculate them again on retry. |
| J7 | Decision 23 requires the staff identity from Enigma. Decision 15 fails closed on an Enigma timeout. No role is locked for running or skipping the daily batch. | Rule change | Lock the actor and the role for an attended or unattended run. This batch does not call Enigma. A missing `actor_id` fails closed and is not audited. A supplied person id is stored. |
| J8 | Nothing requires recognition dates to be consecutive calendar days. | Decide later | Lock whether a calendar day that was never started blocks a later date. This batch allows the gap when no unfinished run is outstanding. |
| J9 | A recognition date whose batch has finished cannot be started again, including when accounts failed. | Rule change | Lock whether a finished day can be repeated. This batch refuses the second start so the day is not calculated twice. |
| J10 | No alert channel or crash timeout is locked. | Decide later | Lock how an operator is notified, and how a killed run is distinguished from a run that is still working. The alert is a stored row returned by the status query. A hard stop leaves the run in progress. The alert row is written when a later start is refused or the run is skipped. No timeout is applied. |
| J11 | Communication section 4 also requires the last status of a batch or UI action by account. | Code change | Add the account query and the UI-action status before production. This batch queries by organisation only. |

## Restructure (Agent G)

`docs/LOCKED_DECISIONS.md` on this tree contains sections 1 to 29. G1 is closed.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| G2 | Decision 25 does not say whether a restructure agreement receives a new loan number. | Decide later | Lock the loan-number rule. This path does not allocate a loan number. |
| G3 | Decision 13 requires an in-Act check of the supplied rate. This path stores the rate and does not run that check. | Code change | Run the calculation-engine check when that engine is on this branch. Do not add a new maximum here. |
| G4 | Decision 23 does not name the role that may restructure. | Rule change | Name the role. This path records the roles presented and does not invent a role name. |
| G5 | A payment-frequency change alone is not locked as a restructure or as a collection campaign. | Rule change | Lock the classification. This path fails closed and creates no agreement. |
| G6 | The ledger stores a balance as the sum of entries. This path transfers the outstanding balance it is given. | Code change | Post the transfer as ledger entries when the branches are combined. |
| G7 | The new agreement's live status token is not locked. | Decide later | Lock the token. This path stores `active`. The original is stored as `restructured`. |
| G8 | This path freezes elections it is given. It does not read the organisation or product election store. | Code change | Resolve Decision 19 from that store when it is on this branch. Missing values already fail closed. |
| G9 | Decision 28's five-business-day notice is locked for a collection campaign. It is not locked for a consented restructure. | Decide later | This path requires consent and does not add a notice interval. |
| G10 | A naive `recognised_at` is reported on the response and is not written to the audit log, because Decision 1 gives it no Johannesburg day. | Code change | Keep the failure visible to operators once a timestamp rule for an unusable clock is locked. |

Open points D1 and D3 and open issue C4 apply here and are not repeated. D1: the rate integer is stored and is not a locked wire format. D3: an identity that differs from the original freeze fails closed. C4 is closed by Decision 19: an unset residual threshold fills R100. The restructure path uses that same fill.
S1 is closed. `Ledger.quote_settlement` delegates to the calculation engine. `Documents.settlement_quote` calls that method. There is still one quote formula.

## Early settlement (Agent F)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| F1 | The five-business-day quote window is orchestration section 7 and section 113 (`binding_until`). It is not a numbered paragraph in the locked decisions. | Decide later | Add the window to the locked decisions when that text is next revised. Do not treat this row as a new lock. |
| F2 | Decision 1 does not say whether interest inside the five-day window runs to the quote as-of date or to a later receipt date. This path keeps the quoted as-of amount and does not accrue the days in between. | Rule change | Say which date is the settlement date for interest. |
| F3 | A receipt above the quote has no locked home on this path. Decision 4 sends an ordinary surplus to Laybye and consolidates when the Laybye covers the settlement balance. That consolidation is not this receipt. The surplus is refused and not allocated. | Decide later | Lock where a settlement surplus goes, or confirm that only an exact match is a settlement. |
| F5 | `Documents.settlement_quote` does not take repo rows. The quote route rejects a non-empty repo list. An unsecured execute can still accrue with repos, then fail closed when that accrual does not match the quote. | Code change | Give the quote the same repo rows the accrual uses, or reject repos on execute as well. |
| F6 | A naive recognition timestamp, and an unknown agreement id, are returned as failures and are not written to the audit log. The log needs an organisation and an aware timestamp. | Code change | Seal those two failures once there is a defined actor and an aware timestamp to attach. |
| F7 | The calculation engine rounds each interest bill and clears the unbilled remainder. The ledger rounds the cumulative memo. On 1 March to 10 April 2026 the two totals matched (6 667 cents). A one-cent difference fails closed. No balancing journal is posted. | Code change | Use one rounding rule for both books, or record that a one-cent difference stays a refusal. |




## Staff UI (Agent K)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| K1 | No route records the daily calculation batch. The batch screen calls `GET /v1/staff/organisations/{id}/audit` and reports that no batch run is stored. It does not accrue, capitalise, or flag default. | Code change | A batch module must record start, finish, accounts processed, accounts failed, and a reason per failure before the screen can show a run. |
| K2 | `lms.collection_campaigns.api.dispatch` has no list or read route. The list and the edit form read `CollectionCampaigns.campaigns` for the signed-in organisation. They do not apply overlap, notice, or rate rules. | Code change | Add a read to the collection-campaign route. The screen should call that route. |
| K4 | `STAFF_UI_REPORTED` is not in `ref_audit_event_type`. The in-process audit log accepts it. A database insert would fail. `CAMPAIGN_CREATED` and the other Layer 2 event types are in the same position. | Database change | Add the event codes before those rows are inserted. |
| K5 | The collection-campaign branch still names its migration `0008_collection_campaigns.sql`. This branch names it `0009_collection_campaigns.sql` so it does not share 0008 with `0008_layer2_staff.sql`. | Database change | Keep 0009 when the collection-campaign branch is merged. Do not restore the 0008 filename beside the staff migration. |
| K7 | Decision 3 on this file says every campaign has an end date. Section 28 allows an open-ended collection campaign. The existing collection-campaign route accepts a null end date. The screen sends null when the field is blank and shows the route's result. | Rule change | Name which sentence applies to a collection campaign. The screen does not choose. |
| K8 | The audit extract accepts the Layer 2 write roles and does not accept `lms.collection_campaign.write` on its own. No batch-status role is locked. | Decide later | An operator who holds only the collection-campaign role cannot open the batch screen. Lock a role if that operator must see batch status. |
| K9 | A blank NCR number is refused by the staff route as `ncr_registration_number is required` before the service sentence that says the number is compulsory. A number of all zeros, including `0000000` and `NCRCP0000`, is accepted by that route. | Decide later | The screen shows the route's reason. The two refusal sentences name the same blank field. |

## Closed

The S2 row below is the merged-smoke initiation quote. The collection-process S2 is the later row labelled S2 (collection process). They are different items. No id was renumbered.

| ID | Resolution |
|----|------------|
| C4 | Decision 19. The residual write-off threshold has a platform default of R100. An unset organisation value and an unset product value fill R100. A stored value, including zero, is kept. A product value overrides the organisation. |
| C5 | Decision 3. `campaign_rate` floors the net at 0 % when the discount is above the base. A negative rate is still refused. |
| C6 | `resolve_residual_threshold_cents` fills 10 000 cents when both levels are null. |
| C7 | Decision 19. Booking fails closed when the in-duplum trigger is unset on both the organisation and the product. |
| N1 | `Documents.statement_issued` reports whether that period is already stored. It does not call `issue_statement`. |
| N6 | Decision 27. Issuing a statement calls `Notifications.push` when the consumer is registered. The message is "Your statement is available." An unregistered consumer still receives the statement and is not pushed. |
| S1 (collection process) | Decisions 1, 8, and 26. Orchestration section 2 is accrue, capitalise due amounts, then `Servicing.accept_payment` and `Ledger.post_payment`. |
| S2 | Decision 2. The settlement quote uses the booked initiation fee. A capitalised fee is already part of the loan value and is not added again. A fee that is not capitalised has its outstanding portion added. VAT is included. The client remains accountable for the VAT portion. |
| S2 (collection process) | Decisions 8 and 26. Orchestration section 8 flags a returned unpaid item after write-off. It does not call `Servicing.reverse_payment`. |
| S3 (merged smoke) | Decision 1. A receipt and that day's accrual share a recognition date by capitalising due amounts first, then allocating. The 1 May memo is on the morning balance. No new lock sentence was added. |
| S4 | Decisions 8 and 20. `record_provision` and `open_prescription_review` store the instructed cents or the boolean instruction. A caller-supplied formula is refused. Promise-to-pay and contactability are not inputs. |
| S5 | `docs/LOCKED_DECISIONS.md` on this tree is the full document, sections 1 to 29. It is not the stub. No collection-campaign section was reconstructed from a commit message. |
| S6 | Decisions 1, 8, and 26. `Collections.receive` posts through `Servicing.accept_payment`, which capitalises due amounts before allocation. |
| J1 | `docs/LOCKED_DECISIONS.md` on this tree contains sections 1 to 29, including the collection-campaign section that was already written. The stub is not the rule text. |
| J12 | When `account_ids` is omitted, the daily batch takes loan identifiers from the ledger. If the ledger cannot supply that list, the run fails closed. |
| G1 | `docs/LOCKED_DECISIONS.md` on this tree is the decision text, sections 1 to 29. |
| G11 | Decision 19. `freeze_elections` fills a missing residual write-off threshold with `resolve_residual_threshold_cents`. A stored value, including zero, is kept. |
| K3 | A missing `lms.collection_campaign.write` is returned as `mandate-denied`. The write screens call the route. Timeout and a suspended enrolment still fail closed. |
| K6 | This tree has one `docs/LOCKED_DECISIONS.md` with sections 1 to 29, including the compulsory NCR number and the all-zeros test number in section 21. |
| H2 | Section 29. A non-campaign rate or fee change requires a written notice of at least five business days before it takes effect (section 104(2)). |
| H3 | Section 29. A temporary reduction is stored as a concession or discount that goes to zero when the period ends. The original contractual rate and fees remain effective. Resuming the original rate does not require a second notice. An interest-rate change does not automatically reduce the contractual instalment. |
| M1 | `_book` in `tests/test_settlement_readvance.py` sets `in_duplum_trigger` to `collections_default` on the booking settings before `POST /v1/agreements`. The ten re-advance tests pass. Decision 19 and the booking path are unchanged. |
| P4 | Decisions 1 and 8. Interest that has accrued up to the due date is due on that date. It is capitalised before the receipt is allocated. |
| J3 | Decision 1. Capitalise due amounts, allocate a receipt recognised that day, then run the morning default check. A receipt recognised on the flag date is visible to the check. The daily batch does not take receipts; it checks receipts already posted. |
| F4 | Decision 7. A settlement closes any open in-duplum episode. The ceiling flag and the warning are cleared. The discount fall-away flag is left as it is. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 18 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 16 | Update docs/LOCKED_DECISIONS.md or docs/ORCHESTRATION.md. These rows need a new lock sentence. They were not edited. |
| Code change | 10 | Update the existing functions. These rows still need a choice the lock does not make, or a wiring the lock does not specify. |
| Database change | 3 | Add a classification column, the staff audit event codes, or keep the migration filenames as they are. |

All agents have completed. All issues are recorded so they can be closed in a single pass before production.
S1, S2, S4, S5, and S6 under Collection-process removal are closed. Collection-process S3 stays open: Decisions 8 and 23 still attribute promise-to-pay and contactability reporting and audit to the LMS, and the collections split says the LMS does not store them. Rewriting those sections would change locked text. That S3 is not the merged-smoke S3.
The merged smoke added C7, N6, and its own S1, S2, and S3. Early settlement closed the merged-smoke S1. Pull request 48 closed C4, C6, C7, the merged-smoke S2, H2, and H3. Those closures are the locks in Decisions 2, 19, and 29. Merged-smoke S3 is closed by the existing Decision 1 order. No id was renumbered.
J1, J3, and J12 are closed. J2, J5, J6, J7, and J9 stay open because each needs a new lock sentence. J11 stays open: Communication section 4 requires status by account and UI-action status, and the query shape is not specified.
G1 and G11 are closed. G3, G6, G8, and G10 stay open. G3 would add an in-Act maximum the issue forbids inventing. G6 would invent the journal that transfers a restructure balance. G8 still freezes the elections it is given. G10 waits for a timestamp rule for an unusable clock.
The restructure flow is orchestration section 10. The daily batch is section 9. The settlement receipt is section 11. The steps are unchanged.
F4 is closed. F1, F2, F3, F5, F6, and F7 stay open. F5 has two options and the lock does not choose. F6 needs an actor and an aware timestamp that are not locked. F7 asks whether to align the two books or keep the one-cent refusal. Decision 17 says the same half-up rule applies everywhere, and the two books were not rewritten in this pass.
K3 and K6 are closed. K1 and K2 stay open: the batch screen still reads the audit route, and the collection-campaign route still has no list or read. K5 is not closed. On this tree the collection-campaign migration stays `0008_collection_campaigns.sql`, Layer 2 staff stays `0009_layer2_staff.sql`, the re-advance stays `0010_settlement_readvance.sql`, and the in-duplum clip stays `0011_in_duplum_ceiling.sql`.
M1 is closed. N1 and N6 are closed. C5 is closed. S4 is closed.
`test_same_day_capitalisation_is_applied_before_the_receipt` and `test_rejected_statement_leaves_no_interest_bill` pass. The two Layer 1 readings, J3, P4, and F4 are the sentences locked in Decisions 1, 4, 6, 7, 8, and 13. A receipt counts only toward its attributed due date, and a section 126 part applied to an earlier due amount does not count toward a later due date. After due section 126 amounts, the remainder goes to the Laybye, and the partial-prepayment election applies only to a remainder that is not sent to a linked Laybye. Interest accrued up to the due date is capitalised before the receipt. A settlement closes any open in-duplum episode and clears the ceiling flag.
