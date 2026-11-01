# LMS Open Issues

Issues that are acceptable for dummy and test implementations but must be closed before production.

Each issue is classified as:
- **Decide later**: a rule or design choice that is not yet needed. Close when the case becomes real.
- **Rule change**: a locked decision must be updated before production.
- **Code change**: existing code must be updated before production.
- **Database change**: a schema or migration change is required before production.

Last updated: 2026-11-01

No open rows remain. The readings are in `docs/LOCKED_DECISIONS.md`. No id was renumbered. The two Layer 1 smoke gaps are closed with P4, J3, and F4.

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
| D1 | Decision 13. Day-1 values are integer basis points, a term count plus a payment frequency, and APP- plus eight digits. This is not a statutory wire format. |
| D2 | Decision 15. Organisation context returns the organisation id and the company registration number. It does not return a service address. |
| D3 | Decision 16. The frozen name, ID number, and service address are the Enigma booking read. |
| N2 | Decision 15. The registration check returns whether the consumer is registered. It does not return email or mobile. |
| N3 | Decision 12. One month is a calendar month. The statement path does not count thirty days. |
| N4 | Decision 21. The statement table has no classification column. The extract reads the agreement classification. The caller supplies pure hosting. |
| N5 | Decision 27. The NCR pattern, call-centre role, Enigma page URLs, and push-provider action stay unset. |
| C1 | Decision 3. A qualifying loan uses the campaign fall-away. Otherwise the organisation election applies, and a product value overrides it. |
| C2 | Decision 3. More than one campaign period on the recognition date fails closed. Nothing is stored. |
| C3 | Decisions 3 and 13. The contractual rate stays the supplied rate. The campaign net is the calculation rate. Both are stored. |
| P1 | Decision 19. `debit_orders_enabled` is the automated-collections switch. It does not change allocation. |
| P2 | Decision 25. The Day-1 loan number is a 12-digit sequence starting at 1. The debit-order line reads the amount still outstanding on the due date. |
| P3 | Decision 26. Record 50 for EFT and DebiCheck. Hash modulo 10**12. A credit-life receipt is stored as accepted and is not posted to an insurer. |
| R1 | Decision 21. `short_term` and `unsecured` require the NCR number. `zero_cost` and `cpa_layby` do not. Omitted pure hosting fails closed. |
| R2 | Decision 8. The Form 39 write-off cell stays empty. The journal is not mapped onto that cell. |
| S3 | Decisions 8 and 23. The LMS does not store promise-to-pay or contactability and does not accept them as provisioning or prescription inputs. Those locked sentences were not rewritten. |
| J2 | Decision 1. The recognition date is 00:00 Africa/Johannesburg. |
| J4 | Decision 30. The batch morning check is `default_check`. The batch does not call `Collections.observe`. |
| J5 | Decision 30. Account failures on a finished batch do not block the next date. An unfinished run does. |
| J6 | Decision 30. A retry walks every account through the steps again. |
| J7 | Decision 30. A missing `actor_id` fails closed and is not audited. A supplied person id is stored. No role name is invented. |
| J8 | Decision 30. A calendar day that was never started does not block a later date. |
| J9 | Decision 30. A finished recognition date cannot be started again. |
| J10 | Decision 30. The alert is a status-query row. No timeout is applied. |
| J11 | Decision 30 and Communication section 4. Batch status can be read by account. UI-action status is the last restructure status for the agreement, and the last recorded action for the organisation. |
| G2 | Decision 25. A restructure keeps the original loan number and copies the application number. |
| G3 | Decision 13. The restructure path runs the engine's prescribed monthly-rate check. It does not add a maximum. |
| G4 | Decision 23. The path records the roles it is given and does not invent a role name. |
| G5 | Decision 28. A frequency-only change is neither a restructure nor a collection campaign. |
| G6 | Decision 13. The outstanding balance moves, in integer cents, from the original record to the new record. No restructure journal is named, so none is posted. |
| G7 | Decision 13. The new agreement is `active`. The original is `restructured`. |
| G8 | Decision 19. When no resolved row is supplied, the path reads the organisation election and the product override. |
| G9 | Decisions 13 and 28. A consented restructure requires consent and a consent date. It does not add the collection-campaign notice. |
| G10 | Decision 1. A naive `recognised_at` is reported and is not written to the audit log. |
| F1 | Decision 2. A settlement quote is binding for five business days. The caller supplies the holidays. |
| F2 | Decision 2. Early-settlement interest runs to the quote as-of date. |
| F3 | Decision 2. An early-settlement receipt must equal the quoted total. |
| F5 | Decision 2. A non-empty repo list is refused on the quote and on execute. |
| F6 | Decision 2. A naive timestamp and an unknown agreement id are returned as failures and are not audited. |
| F7 | Decision 17. A one-cent difference between the two half-up books stays a refusal. No balancing journal is posted. |
| K1 | The batch screen reads `BatchService.status`. It does not accrue, capitalise, or flag a default. |
| K2 | The collection-campaign route has a list and a read. The screens call those routes. The read does not apply overlap, notice, or rate rules. |
| K4 | `0012_staff_ui_reported.sql` inserts `STAFF_UI_REPORTED`. Migrations 0008 to 0011 are not renumbered. |
| K5 | Prefixes stay unique: `0008_collection_campaigns.sql`, `0009_layer2_staff.sql`, `0010_settlement_readvance.sql`, `0011_in_duplum_ceiling.sql`. |
| K7 | Decision 3's end date is the pricing campaign. Decision 28's null end date is an open-ended collection campaign. |
| K8 | Decision 23. An operator who holds only `lms.collection_campaign.write` cannot open the batch screen. |
| K9 | Decision 21. A blank NCR number is refused. A non-blank value, including all zeros, is accepted. |
| Layer 1 attribution | Decision 6. A receipt counts only toward the due date it is attributed to. |
| Layer 1 Laybye | Decisions 4 and 13. After due section 126 amounts, the remainder goes to the Laybye. |


## Summary

| Classification | Count | Action before production |
|----------------|-------|--------------------------|
| Decide later | 0 | None remain. |
| Rule change | 0 | None remain. |
| Code change | 0 | None remain. |
| Database change | 0 | None remain. |

Every row that was open on 31 October 2026 is closed. No id was renumbered. Already locked sentences were not rewritten. The two Layer 1 smoke gaps, P4, J3, and F4 stay closed. Collection-process S3 is closed by the added sentences in Decisions 8 and 23: the LMS does not store promise-to-pay or contactability and does not accept them as inputs. Decisions 8 and 23 still name those facts. Merged-smoke S3 stays the Decision 1 order.
`0012_staff_ui_reported.sql` adds `STAFF_UI_REPORTED`. The earlier migration names stay `0008_collection_campaigns.sql`, `0009_layer2_staff.sql`, `0010_settlement_readvance.sql`, and `0011_in_duplum_ceiling.sql`.
