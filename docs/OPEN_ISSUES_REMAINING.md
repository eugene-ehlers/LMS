# Remaining open items

Read on 1 November 2026 (Africa/Johannesburg) after the closures on this branch. No open item remains. No id was renumbered. Readings already locked before this pass were not rewritten. P4, J3, F4, and the two Layer 1 smoke gaps were already closed and stay closed.

Each id below is closed by the sentence now in `docs/LOCKED_DECISIONS.md`, or by the code that follows that sentence. Amounts are integer cents. The recognition date is 00:00 Africa/Johannesburg.

| ID | Where it is closed |
|----|--------------------|
| D1 | Decision 13. Day-1 dummy values are integer basis points, term count plus payment frequency, and APP- plus eight digits. |
| D2 | Decision 15. Organisation context does not return a service address. |
| D3 | Decision 16. The frozen identity is the Enigma booking read. |
| N2 | Decision 15. The registration check does not return email or mobile. |
| N3 | Decision 12. One month is a calendar month. The path does not count thirty days. |
| N4 | Decision 21. No classification column was added to `lms.client_statement`. The extract reads the agreement classification. |
| N5 | Decision 27. Those contracts stay unset. |
| C1 | Decision 3. A qualifying campaign's fall-away applies. Otherwise the organisation election applies, and a product value overrides it. |
| C2 | Decision 3. Overlapping campaigns fail closed. Nothing is stored. |
| C3 | Decisions 3 and 13. The contractual rate stays the supplied rate. The campaign net is the calculation rate. |
| P1 | Decision 19. `debit_orders_enabled` is the automated-collections switch. It does not change allocation. |
| P2 | Decision 25. The Day-1 loan number is a 12-digit sequence starting at 1. |
| P3 | Decision 26. Record 50, hash modulo 10**12, credit-life receipt stored and not posted to an insurer. |
| R1 | Decision 21. `short_term` and `unsecured` require the number. `zero_cost` and `cpa_layby` do not. |
| R2 | Decision 8. The Form 39 write-off cell stays empty. |
| S3 | Decisions 8 and 23. The LMS does not store promise-to-pay or contactability and does not accept them as inputs. The older sentences that name those facts were not rewritten. |
| J2 | Decision 1. 00:00 Africa/Johannesburg. |
| J4 | Decision 30. The batch morning check is `default_check`. |
| J5 | Decision 30. Finished account failures do not block the next date. |
| J6 | Decision 30. A retry walks every account through the steps again. |
| J7 | Decision 30. A missing actor id fails closed and is not audited. |
| J8 | Decision 30. A never-started day does not block a later date. |
| J9 | Decision 30. A finished day cannot be started again. |
| J10 | Decision 30. The alert is a status row. No timeout is applied. |
| J11 | Decision 30. Batch status by account filters stored failures. UI-action status is the restructure last status. |
| G2 | Decision 25. A restructure does not allocate a second loan number. |
| G3 | Decision 13. The path runs the engine's prescribed monthly-rate check and adds no maximum. |
| G4 | Decision 23. No role name is invented. |
| G5 | Decision 28. A frequency-only change is neither a restructure nor a collection campaign. |
| G6 | Decision 13. The balance moves in integer cents on the agreement records. No journal is named, so none is posted. |
| G7 | Decision 13. `active` and `restructured`. |
| G8 | Decision 19. A missing supplied row is read from the organisation and product election store. |
| G9 | Decisions 13 and 28. Consent and a consent date. No collection-campaign notice. |
| G10 | Decision 1. A naive clock is reported and is not audited. |
| F1 | Decision 2. Five business days. The caller supplies the holidays. |
| F2 | Decision 2. Interest runs to the quote as-of date. |
| F3 | Decision 2. The receipt must equal the quoted total. |
| F5 | Decision 2. Execute refuses a non-empty repo list, as the quote already does. |
| F6 | Decision 2. A naive timestamp and an unknown agreement are failures and are not audited. |
| F7 | Decision 17. A one-cent difference stays a refusal. No balancing journal is posted. |
| K1 | The batch screen reads `BatchService.status` and does not run the steps. |
| K2 | The collection-campaign list and read routes return the stored campaign. |
| K4 | `0012_staff_ui_reported.sql` inserts `STAFF_UI_REPORTED`. |
| K5 | Migration prefixes stay unique. `0008` through `0011` were not renamed. |
| K7 | Decision 3 is the pricing campaign. Decision 28 allows an open-ended collection campaign. |
| K8 | Decision 23. The collection-campaign write role alone cannot open the batch screen. |
| K9 | Decision 21. A blank NCR number is refused. All zeros are accepted. |
