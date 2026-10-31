# Remaining open items

Read from `docs/OPEN_ISSUES.md` and `docs/LOCKED_DECISIONS.md` on 31 October 2026 (Africa/Johannesburg), then checked against the code on this tree. Closed rows are omitted. No reading was added, and no fix is in this list.

The open table has 50 rows: 18 decisions (Decide later), 19 rule changes, 10 code changes, and 3 database changes. The summary also records two Layer 1 smoke gaps that have no id. Those two are at the end.

Collection-process S3 is the open S3. Merged-smoke S3 is closed.

## Decisions

### D1

The wire format for rate, term, and application number is not locked.

Decision. Options: lock a wire format when a real decision engine is integrated, or leave the contract unset until then. The dummy stores the rate as integer basis points (`FIXED_PERIODIC_RATE_BPS` is 240), the term as `term_count` plus `payment_frequency`, and the application number as `APP-` plus eight digits.

### D2

Organisation context does not return a service address. The booking identity read does.

Decision. Options: Enigma organisation context returns addresses, or it does not. `EnigmaDummy._organisation_context` returns the organisation id and the company registration number. `identity_for_booking` returns the service address. Decision 15 says Enigma does not hold addresses, telephone numbers for unregistered consumers, or payment-account details.

### D3

When the name or ID number on the application differs from the Enigma booking read, which value is frozen is not locked.

Decision. Options: freeze the application value, freeze the Enigma booking read, or reconcile them. `Servicing.book` freezes `identity.full_name`, `identity.id_number`, and `identity.service_address` from the Enigma booking check. The dummy does not compare an application name with that read.

### N2

Enigma has no consumer-registration operation that avoids contact details.

Decision. Options: Enigma exposes a registration check that returns no email or mobile, or the LMS keeps a dummy until that operation exists. `EnigmaStub.consumer_registered` returns `bool(self.registered)` and fails closed on timeout, an ambiguous status, or a suspended enrolment. It does not return email or mobile. Decision 27 sends the statement-ready push only when the consumer is registered.

### N5

The NCR character format, the call-centre role name, the Enigma page URLs, and the machine action for the push are not locked.

Decision. Options: lock each contract when the real Enigma and push provider are integrated, or leave them unset. This tree does not store an NCR character pattern, a call-centre role name, an Enigma page URL, or a push-provider action. `Notifications.push` records the message "Your statement is available." and does not call a provider.

### P2

The loan-number character pattern is not locked, and the debit-order loan line does not read a stored contractual instalment.

Decision. Options: lock the loan-number pattern when the numbering scheme is finalised, or keep the outstanding-amount line. `LoanNumberSeries` issues a 12-digit sequence starting at 1. `instalment_outstanding_cents` reads the amount still outstanding on that due date. Decision 25 requires a sequential LMS number linked to the application number and allows a company prefix and a month-year. Decision 13 requires the contractual instalment to be stored.

### P3

The published Bankserv layout does not name a DebiCheck record type or a hash algorithm, and the consumer homing account, the 10-character abbreviated name, and the credit-life insurer hand-off are not locked LMS fields.

Decision. Options: lock the Bankserv layout and the insurer hand-off when the rail and insurer contracts exist, or keep the current file. `bankserv.py` writes record 50 for both EFT and DebiCheck and hashes homing account numbers modulo 10**12. A missing homing account or abbreviated name fails closed. A credit-life premium receipt is stored as `insurer_accepted` and is not posted to an insurer.

### R2

The ledger can post a full write-off journal. The Form 39 write-off cell stays empty.

Decision. Options: include write-offs in Form 39 when the real layout is confirmed, or leave that cell empty. `form39.py` sets `write_offs` to `None` and says a write-off journal is not mapped onto that cell.

### J4

The morning default check has no locked module name.

Decision. Options: name the module. The daily batch calls `default_check`. Orchestration section 3 calls `Collections.observe` when a collections default is flagged. The batch does not call `Collections.observe`.

### J8

Nothing requires recognition dates to be consecutive calendar days.

Decision. Options: a calendar day that was never started blocks a later date, or a gap is allowed when no unfinished run is outstanding. `BatchStore.start_run` blocks an in-progress run and an unresolved incomplete run on another date. It does not require the previous calendar day to have a run.

### J10

No alert channel and no crash timeout are locked.

Decision. Options: lock how an operator is notified and how a killed run is distinguished from a run that is still working. The alert is a row in `batch_alerts`, returned by the status query. A hard stop leaves the run `in_progress`. The alert row is written when a later start is refused or the run is skipped. No timeout is applied.

### G2

Decision 25 does not say whether a restructure agreement receives a new loan number.

Decision. Options: allocate a new loan number, keep the original number, or leave the rule unset. The restructure path copies `application_number` onto the new agreement and does not call `LoanNumberSeries`.

### G7

The live status token of a restructured agreement is not locked.

Decision. Options: lock the token. The new agreement is stored as `active`. The original is stored as `restructured`.

### G9

Decision 28's five-business-day notice is locked for a collection campaign. It is not locked for a consented restructure.

Decision. Options: require that notice on a consented restructure, or require consent only. The restructure path requires `client_consent` true and a consent date. It does not add a notice interval.

### F1

The five-business-day quote window is orchestration section 7 and section 113 (`binding_until`). It is not a numbered paragraph in the locked decisions.

Decision. Options: add the window to the locked decisions when that text is next revised, or leave it in the orchestration note. `binding_until` is what the quote stores. This row is not a new lock.

### F3

A receipt above the settlement quote has no locked home on the early-settlement path.

Decision. Options: send the surplus somewhere, or accept only an exact match. Decision 4 sends an ordinary surplus to Laybye and consolidates when the Laybye covers the settlement balance. That consolidation is a different receipt. Early-settlement execute raises `quote-mismatch` when `cents` is not the quoted total, and the receipt is not allocated.

### K8

The staff audit extract accepts the Layer 2 write roles. It does not accept `lms.collection_campaign.write` on its own. No batch-status role is locked.

Decision. Options: lock a batch-status role if an operator who holds only the collection-campaign role must see batch status, or leave that operator off the batch screen. `require_staff_role` accepts `lms.campaign.write`, `lms.elections.write`, `lms.compliance.write`, and the two ceiling write roles.

### K9

A blank NCR number is refused by the staff route before the service sentence that says the number is compulsory. A number of all zeros is accepted.

Decision. Options: the two refusal sentences name the same blank field, which the screen already shows as the route's reason. The route `_text` raises `ncr_registration_number is required`. `_ncr_present` raises the Decision 21 compulsory sentence for a blank and accepts a non-blank value, including `0000000` and `NCRCP0000`. Decision 21 says the number is compulsory and that a test number of all zeros may be used.

## Rule changes

Each of these needs a new sentence in `docs/LOCKED_DECISIONS.md` or `docs/ORCHESTRATION.md`. The options below are the ones already written in the open row. The current code is what this tree does while that sentence is absent.

### N3

"One month" between successive Day-1 statements has no day count or calendar boundary.

Rule change. Options: a calendar month, or 30 days from the previous statement, locked in Decision 12. `Documents.issue_statement` refuses an overlapping period (`statement-exists`) and refuses a gap that would hide a ledger value date (`statement-gap`). Decision 12 says the maximum period for Day-1 products is one month and does not define the boundary.

### C1

Fall-away choice and trigger are stored on the campaign and also as an organisation election with a product override. The lock does not say which value applies when they differ.

Rule change. Options: the campaign value wins, or the organisation value wins, named in Decision 3 or Decision 19. The campaign row stores `fall_away_choice` and `fall_away_trigger`. `resolve_elections` uses the product choice when the product has one, and otherwise the organisation choice. Intake copies the campaign's fall-away onto the intake row. Decision 3 stores the choice per campaign. Decision 19 also stores it as an organisation election with a product override. Open point 1 records that the document does not say which stored value applies when they differ.

### C2

The lock does not say which campaign applies when more than one period contains the recognition date.

Rule change. Options: the most recent campaign, or fail closed, locked in Decision 3. `record_intake` raises `campaign-ambiguous` when `len(matches) > 1` and does not store the intake. Decision 3 says a loan generated during the campaign period qualifies for the linked campaign. Open point 2 records that the document does not say which campaign applies.

### C3

The lock does not say whether a qualifying loan keeps the decision-engine rate or uses the campaign net.

Rule change. Options: keep the supplied rate, or use the campaign net, locked in Decision 3 or Decision 13. `DecisionIntake` stores `supplied_rate` and `campaign_net_rate`. The intake comment says it does not copy one over the other. Decision 3 defines the campaign price as base less discount. Decision 13 says the LMS uses the rate the decision engine supplies. Open point 3 records that the document does not say which figure is the contractual rate.

### P1

Section 19 does not name `debit_orders_enabled` as the section 4 automation switch.

Rule change. Options: add `debit_orders_enabled` to the Decision 19 elections, or leave the catalogue flag unnamed. The seed catalogue describes it as "Submit debit orders. Does not change allocation." The rail fails closed when the flag is unset and submits no file when it is false. The gaps section of the locked document says the lock does not say that flag is the section 4 switch.

### P4

Whether interest accruing on the due date is itself due that day is unsettled.

Rule change. Options: that day's accrual is due that day, or it is not, locked in Decision 1 or Decision 8. `PaymentRail.capitalise_due_amounts` accrues through the recognition date and then `bill_interest` debits the whole unbilled memo, which includes that day's accrual. Decision 1 says capitalise the day's due amounts, then allocate. The gaps section says the question is not settled beyond that sentence.

### R1

Decision 21 says "micro" and "Laybye/BNPL". The ledger stores `short_term`, `unsecured`, `zero_cost`, and `cpa_layby`. `pure_hosting` is not a column. The map is not locked.

Rule change. Options: lock the classification map in Decision 21, and add `pure_hosting` as a column or as a value the extract can read. `ncr.py` treats `short_term` and `unsecured` as the classifications that require an NCR number, and `zero_cost` and `cpa_layby` as the ones that do not. That map is labelled a template reading. `require_ncr_for_extract` fails closed with `pure-hosting-unset` when `pure_hosting` is omitted and a classification would require the number. Decision 21 requires the number for micro and unsecured personal loans and not for pure hosting or Laybye/BNPL.

### S3

Decision 8 says promise-to-pay adherence and contactability are calculated on LMS data in reporting. Decision 23 lists promise-to-pay and contact as audited LMS changes. The collections split says the LMS does not store them.

Rule change. Options: update Decision 8 and Decision 23 so reporting and audit of those facts are attributed to the collections system. The open row says not to add an LMS store to satisfy the old wording. `ProvisionFacts` has arrears, recency, and months on book. Promise-to-pay and contactability are not fields. Passing them into `record_provision` or `open_prescription_review` raises `TypeError`. Decision 8 and Decision 23 still name those facts on the LMS side.

### J2

Decision 1 says the day starts at 00:00 and does not name a time zone.

Rule change. Options: lock Africa/Johannesburg on Decision 1, or name a different zone. `parse_recognition_date` accepts a calendar date or an instant that is exactly 00:00 Africa/Johannesburg and stores the offset `+02:00`. Any other clock time is refused.

### J3

Orchestration section 1 calls `Servicing.accept_payment` before the default outcome. The daily batch calls accrue, capitalise, and default check only.

Rule change. Options: the morning default check runs after allocation of a receipt recognised the same day, or it does not. `STEPS` is `accrue`, `capitalise`, `default_check`. The batch does not call `Servicing.accept_payment`.

### J5

"If the batch does not complete" does not say whether account failures on a finished batch block the next recognition date.

Rule change. Options: account failures on a finished batch block the next date, or they do not. A finished run is `completed` after account failures are stored, audited as `failed`, and shown as the last failed run. Those failures do not raise the did-not-complete alert and do not block the next date. An unfinished run blocks a later date until that same date is finished or explicitly skipped.

### J6

A retry after an incomplete or skipped run calls accrue, capitalise, and default check again for every account.

Rule change. Options: lock idempotency, or leave a retry able to calculate accounts again. `start_run` allows another run for the same recognition date when the earlier run is incomplete. The new run walks the whole account list through `STEPS`.

### J7

Decision 23 requires the staff identity from Enigma. Decision 15 fails closed on an Enigma timeout. No role is locked for running or skipping the daily batch.

Rule change. Options: lock the actor and the role for an attended or unattended run. The batch does not call Enigma. A missing `actor_id` fails closed in `_require_token` before a run is stored. A supplied person id is stored on the run and on the audit row.

### J9

A recognition date whose batch has finished cannot be started again, including when accounts failed.

Rule change. Options: a finished day can be repeated, or the second start stays refused. `start_run` refuses a second start when `_completed_for` already has a finished batch for that date, so the day is not calculated twice.

### G4

Decision 23 does not name the role that may restructure.

Rule change. Options: name the role. The restructure path records `actor_roles` on the audit payload. It does not invent a role name and it does not call `require_role`.

### G5

A payment-frequency change alone is not locked as a restructure or as a collection campaign.

Rule change. Options: classify a frequency-only change as a restructure, as a collection campaign, or as neither. `_require_contractual_change` fails closed when the payment frequency changed and the term count and instalment did not, and it creates no agreement. Decision 28 says a change that alters the contractual term or the contractual instalment amount is a restructure and is not a collection campaign.

### F2

Decision 1 does not say whether interest inside the five-day window runs to the quote as-of date or to a later receipt date.

Rule change. Options: the settlement date for interest is the quote as-of date, or it is the receipt date. Early-settlement execute capitalises through `stored.as_of` and allocates the quoted total. The calculation engine folds events up to `quote.as_of` and settles on that date. Days between the as-of date and a later receipt date are not accrued on this path.

### F4

The calculation engine closes an open in-duplum episode when it settles. The LMS settlement path does not. Decision 7 depends on the trigger, and a settlement is not named as a close.

Rule change. Options: settlement closes an open episode, or it does not. `lms.calc.ledger` sets `closed_on` on the open episode when the quoted total clears the as-of balances. `lms.settlement.service` has no `closed_on` write. Decision 7 closes a collections-default episode on cure and leaves a contractual-breach episode open.

### K7

Decision 3 says every campaign has an end date. Section 28 allows an open-ended collection campaign.

Rule change. Options: Decision 3's end date applies to a collection campaign, or section 28's open-ended period applies. The collection-campaign route accepts a null `end_date`. `_require_period` treats null as open-ended. The screen sends null when the field is blank and shows the route's result. The screen does not choose which sentence applies.

## Code changes

### J11

Communication section 4 requires the last status of a batch or UI action by account. The daily batch queries by organisation only.

Code change. Today `BatchService.status` returns the organisation's last status, last successful run, last failed run, and open alerts. The restructure module has `last_status` for one agreement. The batch module has no account query and no UI-action status. Communication section 4 says operators can query the last status of any batch or UI action by account or by organisation. The query shape is not specified beyond that sentence.

### G3

Decision 13 requires an in-Act check of the supplied rate. The restructure path stores the rate and does not run that check.

Code change. Today the new agreement stores `contractual_periodic_rate_bps` from the decision-engine supply. The calculation engine refuses a margin, a monthly rate, or a short-term term that exceeds the figures in its models. The restructure path does not call those checks. Decision 13 says the LMS uses the rate it is given and checks that calculations stay within the Act for that rate. The open row says not to add a new maximum here.

### G6

The ledger stores a balance as the sum of entries. The restructure path transfers the outstanding balance it is given.

Code change. Today `_perform` copies `outstanding_balance_cents` onto the new agreement and sets the original balance to 0. It does not post ledger entries. The open row says to post the transfer as ledger entries. The locked decisions do not name the journal lines of that transfer.

### G8

The restructure path freezes the elections it is given. It does not read the organisation or product election store.

Code change. Today `freeze_elections` copies the supplied dict. A missing residual write-off threshold is filled with `resolve_residual_threshold_cents` (Decision 19, R100). Other missing elections fail closed. `lms.staff.elections.resolve_elections` reads the organisation and product stores. The restructure path does not call it. Decision 19 stores those elections at organisation level with an optional product override.

### G10

A naive `recognised_at` is reported on the response and is not written to the audit log.

Code change. Today `recognition_instant` rejects a naive datetime because Decision 1 gives it no Johannesburg day. The failure result carries the reason. The audit write runs only when an aware instant exists. The open row says to keep the failure visible to operators once a timestamp rule for an unusable clock is locked. That timestamp rule is not in the locked decisions.

### F5

`Documents.settlement_quote` does not take repo rows. The quote route rejects a non-empty repo list. An unsecured execute can still accrue with repos, then fail closed when that accrual does not match the quote.

Code change. Today `Settlement._quote` raises `repo-quote-unset` when `repos` is non-empty. `Settlement.execute` passes `repos` into `_accrue_through`. A ledger total that differs from the quote raises `quote-mismatch` and the receipt is not allocated. The open row gives two options: give the quote the same repo rows the accrual uses, or reject repos on execute as well. Decision 11 says an unsecured accrual needs a repo rate and that none is assumed. It does not choose between those two options.

### F6

A naive recognition timestamp, and an unknown agreement id, are returned as failures and are not written to the audit log.

Code change. Today `Settlement.quote` and `Settlement.execute` call `_require_aware` and `_record` before the `try` that calls `_audit_failure`. A naive timestamp raises `timestamp-naive`. An unknown agreement id raises `not-found`. Neither call appends an audit row. Decision 23 says an audit record includes who did it, when, and what was done. The log needs an organisation and an aware timestamp. The open row says to seal those two failures once there is a defined actor and an aware timestamp to attach. Those two attachments are not locked (see J7).

### F7

The calculation engine rounds each interest bill and clears the unbilled remainder. The ledger rounds the cumulative memo. A one-cent difference fails closed. No balancing journal is posted.

Code change. Today `lms.calc.money.to_cents` rounds half-up, and the engine's bill converts that day's unbilled amount and then clears it. `Ledger.bill_interest` sums the memo rands and rounds that sum once with `to_cents`. On 1 March to 10 April 2026 the two totals matched at 6 667 cents. A later one-cent difference is a refusal. Decision 17 says round half-up to cents on billing and apply the same rounding rule everywhere. The open row's options are to use one rounding rule for both books, or to record that a one-cent difference stays a refusal. Decision 17 does not say whether "the same rule" means rounding each bill or rounding the cumulative memo.

### K1

The batch screen calls the staff audit extract and reports that no batch run is stored. It does not accrue, capitalise, or flag default.

Code change. Today `StaffApp._batch` calls `GET /v1/staff/organisations/{id}/audit`. The screen text says no daily-calculation batch route is registered on that screen. `BatchService` records start, finish, accounts processed, accounts failed, accounts at the ceiling, and a reason per account failure. The screen does not call that service. The open row says the screen can show a run once a batch module records those fields.

### K2

`lms.collection_campaigns.api.dispatch` has no list or read route. The list and the edit form read `CollectionCampaigns.campaigns` for the signed-in organisation.

Code change. Today `dispatch` handles create, edit, end, and apply. `_collection_read_gate` says the list and the edit form have no route to call. Those screens read the in-process campaign store. They do not apply overlap, notice, or rate rules on that read. The open row says to add a read to the collection-campaign route and to have the screen call that route. Decision 28 states the campaign rules. It does not specify the read response.

## Database changes

These three rows are database changes in `docs/OPEN_ISSUES.md`. They are not a code change, a rule change, or a decision in that table.

### N4

A stored statement has no section 21 classification and no pure-hosting flag. A blank NCR number fails closed.

Database change. `lms.client_statement` stores organisation, statement id, person, period start, and period end. It has no classification column and no pure-hosting flag. The open row says to add a classification column (`short_term`, `unsecured`, `pure_hosting`, `zero_cost`, `cpa_laybye`) to the statement or the agreement so the NCR exemption can be applied. Decision 21 requires the number for micro and unsecured personal loans and not for pure hosting or Laybye/BNPL. A blank number still fails closed on an extract that requires it (see R1).

### K4

`STAFF_UI_REPORTED` is not in `lms.ref_audit_event_type`. The in-process audit log accepts it. A database insert of that code would fail.

Database change. `StaffApp._report` appends `STAFF_UI_REPORTED` to the in-process log. No migration inserts that code. `0009_layer2_staff.sql` does insert `CAMPAIGN_CREATED`, `CAMPAIGN_EDITED`, `CAMPAIGN_ENDED`, `ELECTION_CHANGED`, `COMPLIANCE_CHANGED`, `CEILING_CHANGED`, and `DECISION_INTAKE_STORED`. `0008_collection_campaigns.sql` inserts `COLLECTION_CAMPAIGN_CHANGED`. The open row's note that those Layer 2 codes are also missing is not the schema on this tree. The row stays open because `STAFF_UI_REPORTED` is still absent from the reference table.

### K5

The open row says to keep a `0009` collection-campaign migration so it does not share `0008` with the staff migration.

Database change. This tree has `0008_collection_campaigns.sql`, `0009_layer2_staff.sql`, `0010_settlement_readvance.sql`, and `0011_in_duplum_ceiling.sql`. There is no `0009_collection_campaigns.sql`. The campaigns file and the staff file do not share a number. The row is still open. It tells a later merge not to restore a colliding `0008` filename beside the staff migration. This list does not rename any file.

## Recorded in the summary, no id

`test_layer1_smoke` still fails. The summary records two gaps. They have no row id. The smoke leaves them as gaps and does not change a locked rule.

### Attributed receipt and the collections default

The collections default closed while R90.00 of principal was still unpaid, because the R219 receipt is one amount attributed to 1 May and collections counts that whole amount, including the portion section 126 applied to the 30 April interest.

Decision. Options, as the smoke states them: a receipt that section 126 splits across due dates counts in full toward the single attributed due date, or it does not. Locked section 6 does not say which. The current collections count uses the whole attributed amount. The smoke does not choose a split.

### Laybye remainder and partial prepayment

Once a Laybye exists, a receipt pays due section 126 amounts and the remainder goes to the Laybye. The partial-prepayment election is not applied to that remainder.

Decision. Options, as the smoke states them: the Laybye remainder runs first, or the partial-prepayment election runs first. Locked sections 4 and 13 do not say which. The current receipt path sends the remainder to the Laybye.
