# Technical overview

For a reviewer of the Day-1 loan management system. The rules are `docs/LOCKED_DECISIONS.md`. This note does not change them. Figures below are the six staff-demo moments, which run on stubs. Amounts are integer cents. Instants are Africa/Johannesburg.

On `main`, `docs/LOCKED_DECISIONS.md` is a stub. The rules cited here are the restored document the demo runs against (sections 1–29, last updated 30 October 2026). A later commit on `cursor/close-remaining-open-items-bf6a` adds further sentences, including that interest accrued up to the due date is due that date. Where the two files differ, this note names the difference and picks no new reading.

## Layers 0–4

The tree that runs the demo uses this numbering. Earlier drafts used “Layer 3” for an onboarding design and “Layer 4” for a payment-rail design. On this tree, payment rails are Layer 3.

| Layer | Owns | Leaves alone |
| --- | --- | --- |
| 0 | Calculation engine, ledger, calendar, and elections. Daily accrual, NCA caps, section 126, the in-duplum ceiling, and the account. | Person and organisation identity. Those stay in Enigma. |
| 1 | Statements, the Laybye parent and child, collections default and the in-duplum episode, and regulatory reads (SACRRA catalogue, Form 39 readiness, audit extract). | A second interest, fee, VAT, or in-duplum formula. It calls Layer 0. |
| 2 | Pricing campaigns, collection campaigns, elections with a product override, compliance, operational ceilings, and the staff commands that write them. | A booked agreement. A campaign edit writes the campaign row and an audit row. |
| 3 | Payment rails: the debit-order file and receipt intake. Accrue, bill interest that is due, levy the service fee that is due, then allocate that date’s receipts in recognition sequence. | The network. A later live rail supplies `submit` and `take_receipts`. |
| 4 | The statement-ready push (Decision 27). A registered consumer is told the monthly statement is available. The message has no collection content. | Collection notices, which stay with the collections system. This demo tree has no notifications module, so the demo sends no push (open issue N6). |

Onboarding sits beside those layers. It is the LMS capture that follows Enigma: NCR number, trading name, addresses, telephone, payment details, brand, and elections.

## Enigma boundary

Decision 15. Enigma is registration, sign-on, logout, passwords, the link between a person and an organisation, and the roles that grant access. The LMS stores `person_id` and `organisation_id`. A timeout, an ambiguous status, or a suspended enrolment fails closed.

Compliance and brand live in the LMS. Enigma does not hold the NCR number, trading name, addresses, telephone numbers for unregistered consumers, payment-account details, brand assets, operational ceilings, or campaigns. Organisation context returns the organisation id and the company registration number. The booking read supplies the name, ID number, and service address frozen on the agreement (Decision 16). A later Enigma change leaves that agreement as it was frozen.

The demo staff session is the temporary bypass. `POST /staff/session` holds `person-test-001`, `org-test`, the write roles, and `enigma_status=active` in the browser. Enigma is not connected. The form has no email and no password, and it writes no LMS record.

## Statements and payments, as the demo runs them

A missing election, identity, interest cap, VAT rate, compliance row, debit outcome, or loan number fails closed and stores nothing for that step. The organisation-settings table stays empty. The book form supplies the elections. Moments 2 to 4 and moment 6 share one process. The browser book at `/exercise` is another process and another agreement id. The HTML pages omit opening balances, the section 126 split, Laybye interest, and the in-duplum flag. Those figures are on the functions in the staff demo.

| Moment | What the stub returns |
| --- | --- |
| 2. Book | `DecisionQuoteStub` returns the template 5% monthly rate, `APP-00000001`, and a fixture premium of 199 cents. A fresh process issues loan `000000000001`. Cash advanced 200 000, disbursed 1 April 2026, due 1 May 2026. The form stands in for the Enigma booking read. |
| 3. April statement | 1–30 April 2026. No previous statement: every opening bucket is 0. Closing: principal 200 000, interest 10 000, service 6 900, and 0 on the other buckets. Provider block is the LMS compliance row, NCR `0000000000`. Brand keys `brand/org-test/statement-header` and `brand/org-test/statement-footer`. |
| 4. Receipt, then May | April runs first and bills the interest and service fee this receipt pays. `outcome=success` allocates 21 900 cents on `000000000001`: interest 10 000, service 6 900, principal 5 000. `outcome=failure` allocates nothing. The 1 May statement opens from the April closing and closes at principal 195 000, interest 0, service 0. |
| 5. Laybye | A new ledger. A pre-disbursement receipt on the moment-2 loan returns `already-granted`. On the new pair, 40 000 cents on 10 March is a `laybye_deposit` (hold 40 000, parent principal 0 until grant). After grant and one day: principal 100 000, hold 40 000, interest base 60 000. One parent service fee of 6 900. Child service stays 0. A second April levy returns `service-fee-once` and posts nothing. |
| 6. Collections default | Trigger `collections_default`. On 5 May the ceiling is 195 000, unpaid principal at open. `IN_DUPLUM_CLIP_POSTS` is true and accrued charges are 0, so `clip_in_duplum()` adds no transaction. `observe` writes one `default_flag` and no receipt. |

## Residual write-off threshold

The threshold is client-configurable. The current platform value is R100 (10 000 cents). An unset organisation value and an unset product value fill R100. A stored value, including zero, is kept. A product value overrides the organisation. The demo leaves the field blank, and the fill is 10 000 cents.

The write-off waits for a staff or external-formula instruction, after the last schedule date, when the residual is within the threshold and no in-duplum episode is open. A residual during default follows arrears and in-duplum. A write-off allocates every receipt first and reduces the balance to R0.

## Known open sequencing gaps

Recorded so a reviewer is not surprised. None of these is a second rule.

1. **Same-day order on the servicing statement path.** `test_same_day_capitalisation_is_not_applied_before_the_receipt` ends in `pytest.fail`. Decisions 1 and 8 capitalise the day’s due amounts, then allocate receipts of that day. The Layer 3 rail does that. The servicing statement path follows recognition sequence. A 1 May receipt posted first is allocated on the April balance; the later statement accrues 1 May interest on the reduced principal (315 cents) and can levy a second service fee. The demo issues the April statement first, so the May closing interest and service are 0. A later statement does not reverse or reallocate a receipt already posted (statement gap G9).

2. **Interest accruing on the due date.** The lock the demo runs against still records this as unsettled, past the phrase “capitalise due amounts, then allocate.” The rail bills the whole unbilled memo and substitutes no other figure. The later lock on `cursor/close-remaining-open-items-bf6a` says interest accrued up to the due date is due that date and is capitalised before the receipt. The smoke test remains the record of the gap until that sentence is the file under review.

3. **A refused servicing statement can bill interest first.** `test_rejected_statement_leaves_no_interest_bill` bills interest before it rejects a missing VAT rate. The documents path the demo uses raises `vat-rate-unset`. In the statement tests that refusal leaves only the booking transaction. The two paths are a different sequence.

4. **`allocation.py` still splits a same-day short payment in proportion.** Decision 8 orders due fees as collection costs, default administration, credit insurance, service fee, then initiation, earliest due date first inside a bucket. The ledger does not call that splitter.

5. **The demo loan-number series lives in the process.** `LoanNumberSeries` starts at 1. A new process issues `000000000001` again. Decision 25 requires a sequence that is not skipped, one number per application, with a Laybye distinguished by another indicator. The restart is the in-memory stub.

6. **The statement-ready push is absent on this tree.** Orchestration section 6 calls `Notifications.push` after `Documents.issue_statement` for a registered consumer. Open issue N6: there is no notifications module, and `issue_statement` does not push. Decision 27 still requires that push, with no collection content, once the module is present.
