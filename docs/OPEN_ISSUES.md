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

## Collection-process removal

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| S1 | Orchestration section 2 handles a receipt as Servicing.accept_payment then Ledger.post_payment. Locked sections 1, 8, and 26, the collections split, and orchestration section 1 capitalise due amounts first. The payment rail already does that. | Rule change | Update docs/ORCHESTRATION.md section 2 to the locked capitalise-then-allocate order. |
| S2 | Orchestration section 8 calls Servicing.reverse_payment for a returned unpaid item after write-off. Locked sections 8 and 26 say the item is flagged only, the balance is not reopened, and no recovery is posted. The payment rail already flags only. | Rule change | Update docs/ORCHESTRATION.md section 8 so it does not call reverse_payment on that path. |
| S3 | Decision 8 says promise-to-pay adherence and contactability are calculated on LMS data in reporting. Decision 23 lists promise-to-pay and contact as audited LMS changes. The collections split says the LMS does not store them. After this removal there is no LMS store for reporting to read. | Rule change | Update Decision 8 and Decision 23 so reporting and audit of those facts are attributed to the collections system. Do not add an LMS store to satisfy the old wording. |
| S4 | record_provision and open_prescription_review still run a caller-supplied formula inside the LMS. _facts still derives recency and months on book. Decision 8 says provisioning formulas run outside the LMS and that those figures are not calculated inside it. Promise-to-pay and contactability are no longer inputs. | Code change | Move the formula out, or record that a caller-supplied formula over ledger facts is the allowed instruction. Do not put promise-to-pay or contactability back. |
| S5 | On main, docs/LOCKED_DECISIONS.md is the one-line stub written by f75d1be and ecffee7. The collection-campaign text named in the f75d1be message was never stored. This branch still has the full document through section 27. | Code change | Restore the locked document. Do not reconstruct the missing collection-campaign section from the commit message. |
| S6 | Collections.receive still posts a receipt through Servicing.accept_payment without capitalising due amounts. Payment-rail intake capitalises first. This removal does not change Collections.receive. | Code change | Decide whether Collections.receive is still a receipt path. If it is, capitalise before accept_payment, using the existing ledger calls. |

## Merged smoke

These rows are the contradictions the seven-path smoke produced. S1 was closed by the early-settlement path. S2 is closed. S3 remains.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| S3 | The 1 May interest memo after the R219 receipt was 3.1451612903 rands, on the R1 950 left after the receipt. Sections 1 and 8 treat the day as 00:00 and capitalise before allocating. The receipt path posted before the statement accrued that day. A memo on the R2 000 balance at the start of the day would be 3.2258064516 rands. The memo was not billed. | Rule change | Say which flow wins when a receipt and that day's accrual share a recognition date. |

## Daily batch status (Agent J)

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| J1 | `docs/LOCKED_DECISIONS.md` contains only "See /tmp/locked_updated.md - content too large for this call, will upload in parts if needed". That file is not present. The last complete text is commit `71aac64184500fe55390c3c822bf74c796fa6127` (same body as `401b3c1dacf2373c7a7678ec2b676002b4512c02`). Commit `f75d1be` replaced it with `PLACEHOLDER`. Commit `ecffee7` replaced it with the stub. The commit subject mentions a collection-campaigns section. The section body was never written. | Rule change | Restore the locked decisions text. Add the collection-campaigns section only from wording that is actually supplied. Do not invent that section. The daily batch followed the last complete text plus the communication, orchestration, and collections-split documents, and did not edit the stub. |
| J2 | Decision 1 says the day starts at 00:00 and does not name a time zone. | Rule change | Lock Africa/Johannesburg on Decision 1, or name a different zone. This batch uses Africa/Johannesburg because the batch requirement states it. The stored offset is +02:00. |
| J3 | Orchestration section 1 calls Servicing.accept_payment before the default outcome. The daily batch calls accrue, capitalise, and default check only. | Rule change | Lock whether the morning default check runs after allocation of a receipt recognised the same day. Until then, this batch does not allocate, and the default check cannot see that receipt unless allocation already happened outside the batch. |
| J4 | The morning default check has no locked module name. | Decide later | Name the module. This batch calls `default_check`. It does not call Collections.observe, which section 3 uses when a collections default is flagged. |
| J5 | "If the batch does not complete" does not say whether account failures on a finished batch block the next recognition date. | Rule change | Lock the gate. Until then: a finished batch has completed; account failures are stored, audited as `failed`, and shown as the last failed run; they do not raise the did-not-complete alert and do not block the next date. Only an unfinished run blocks, until a later finish of that same date or an explicit skip. |
| J6 | A retry after an incomplete or skipped run calls accrue, capitalise, and default check again for every account. | Rule change | Lock idempotency. A crash after some accounts were calculated can calculate them again on retry. |
| J7 | Decision 23 requires the staff identity from Enigma. Decision 15 fails closed on an Enigma timeout. No role is locked for running or skipping the daily batch. | Rule change | Lock the actor and the role for an attended or unattended run. This batch does not call Enigma. A missing `actor_id` fails closed and is not audited. A supplied person id is stored. |
| J8 | Nothing requires recognition dates to be consecutive calendar days. | Decide later | Lock whether a calendar day that was never started blocks a later date. This batch allows the gap when no unfinished run is outstanding. |
| J9 | A recognition date whose batch has finished cannot be started again, including when accounts failed. | Rule change | Lock whether a finished day can be repeated. This batch refuses the second start so the day is not calculated twice. |
| J10 | No alert channel or crash timeout is locked. | Decide later | Lock how an operator is notified, and how a killed run is distinguished from a run that is still working. The alert is a stored row returned by the status query. A hard stop leaves the run in progress. The alert row is written when a later start is refused or the run is skipped. No timeout is applied. |
| J11 | Communication section 4 also requires the last status of a batch or UI action by account. | Code change | Add the account query and the UI-action status before production. This batch queries by organisation only. |
| J12 | The run is given its account identifiers. There is no ledger account registry in this repository. An empty list finishes with zero accounts. | Code change | Take the account list from the ledger when the ledger exists, and fail closed if the ledger cannot supply it. |

## Restructure (Agent G)

`docs/LOCKED_DECISIONS.md` on this branch does not contain the locked text. It points at `/tmp/locked_updated.md`, which is not in the repository. The restructure path followed the last complete copy (commit `401b3c1`) and section 28 on `cursor/restore-locked-decisions-ccde`. It did not edit the locked file.

| ID | Issue | Classification | What must change |
|----|-------|----------------|------------------|
| G1 | `docs/LOCKED_DECISIONS.md` on main is a pointer, not the decisions. | Rule change | Restore the decision text. Pull request 35 proposes that restore. |
| G2 | Decision 25 does not say whether a restructure agreement receives a new loan number. | Decide later | Lock the loan-number rule. This path does not allocate a loan number. |
| G3 | Decision 13 requires an in-Act check of the supplied rate. This path stores the rate and does not run that check. | Code change | Run the calculation-engine check when that engine is on this branch. Do not add a new maximum here. |
| G4 | Decision 23 does not name the role that may restructure. | Rule change | Name the role. This path records the roles presented and does not invent a role name. |
| G5 | A payment-frequency change alone is not locked as a restructure or as a collection campaign. | Rule change | Lock the classification. This path fails closed and creates no agreement. |
| G6 | The ledger stores a balance as the sum of entries. This path transfers the outstanding balance it is given. | Code change | Post the transfer as ledger entries when the branches are combined. |
| G7 | The new agreement's live status token is not locked. | Decide later | Lock the token. This path stores `active`. The original is stored as `restructured`. |
| G8 | This path freezes elections it is given. It does not read the organisation or product election store. | Code change | Resolve Decision 19 from that store when it is on this branch. Missing values already fail closed. |
| G9 | Decision 28's five-business-day notice is locked for a collection campaign. It is not locked for a consented restructure. | Decide later | This path requires consent and does not add a notice interval. |
| G10 | A naive `recognised_at` is reported on the response and is not written to the audit log, because Decision 1 gives it no Johannesburg day. | Code change | Keep the failure visible to operators once a timestamp rule for an unusable clock is locked. |
| G11 | Decision 19 fills an unset residual write-off threshold with R100. The restructure path still fails closed and does not fill it. | Code change | Use the same fill as `resolve_residual_threshold_cents`. Do not choose a different default. |

Open points D1 and D3 and open issue C4 apply here and are not repeated. D1: the rate integer is stored and is not a locked wire format. D3: an identity that differs from the original freeze fails closed. C4 is closed by Decision 19: an unset residual threshold fills R100. The restructure path still fails closed and does not fill that default.
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

The S2 in this table is the merged-smoke initiation quote. The collection-process S2 stays open.

| ID | Resolution |
|----|------------|
| C4 | Decision 19. The residual write-off threshold has a platform default of R100. An unset organisation value and an unset product value fill R100. A stored value, including zero, is kept. A product value overrides the organisation. |
| C6 | `resolve_residual_threshold_cents` fills 10 000 cents when both levels are null. |
| C7 | Decision 19. Booking fails closed when the in-duplum trigger is unset on both the organisation and the product. |
| S2 | Decision 2. The settlement quote uses the booked initiation fee. A capitalised fee is already part of the loan value and is not added again. A fee that is not capitalised has its outstanding portion added. VAT is included. The client remains accountable for the VAT portion. |
| H2 | Section 29. A non-campaign rate or fee change requires a written notice of at least five business days before it takes effect (section 104(2)). |
| H3 | Section 29. A temporary reduction is stored as a concession or discount that goes to zero when the period ends. The original contractual rate and fees remain effective. Resuming the original rate does not require a second notice. An interest-rate change does not automatically reduce the contractual instalment. |
| M1 | `_book` in `tests/test_settlement_readvance.py` sets `in_duplum_trigger` to `collections_default` on the booking settings before `POST /v1/agreements`. The ten re-advance tests pass. Decision 19 and the booking path are unchanged. |

## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 18 | Lock the rule or confirm the external contract when the case becomes real. |
| Rule change | 25 | Update docs/LOCKED_DECISIONS.md or docs/ORCHESTRATION.md. |
| Code change | 19 | Update the existing functions, or restore the locked document. |
| Database change | 3 | Add a classification column. |

All agents have completed. All issues are recorded so they can be closed in a single pass before production.
S1 to S6 under Collection-process removal were found while removing collection-process state. They are not new rules. That S1 stays open. The collection-process S2 stays open. It is not the merged-smoke S2.
The merged smoke added C7, N6, and its own S1, S2, and S3. Early settlement closed the merged-smoke S1. Pull request 48 closed C4, C6, C7, the merged-smoke S2, H2, and H3. Those closures are the locks in Decisions 2, 19, and 29. S3 remains. No id was renumbered.
J1 to J12 are the daily-batch gaps. They are not new rules. J1 records that main's locked file was a stub. This tree already has the restored document. That row is not closed here.
G1 to G11 are the restructure gaps. They are not new rules. G1 records that main's locked file was a pointer. This tree already has the restored document. That row is not closed here. G11 records that the restructure path still fails closed after Decision 19 filled an unset residual with R100.
The restructure flow is orchestration section 10. The daily batch is section 9. The settlement receipt is section 11. The steps are unchanged.
F1 to F7 are the early-settlement gaps. They are not new rules.
K1 to K9 are the staff-screen gaps. They are not new rules. K5 is not closed. On this tree the collection-campaign migration stays `0008_collection_campaigns.sql`, Layer 2 staff stays `0009_layer2_staff.sql`, and the re-advance stays `0010_settlement_readvance.sql`.
M1 is closed. `_book` sets `in_duplum_trigger` to `collections_default` before the booking request. The ten re-advance tests pass. Decision 19 and the booking path are unchanged. The three pre-existing smoke failures remain.
