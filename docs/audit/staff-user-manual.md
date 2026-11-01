# Staff user manual

How a staff member runs the test screens. Each step cites the locked decision or the design note it follows. This manual does not add a rule.

The process is `python -m lms.staff_ui` on `127.0.0.1:8765` (`docs/staff-ui/README.md`). The exercise forms are served with that process (`src/lms/runtime.py`). Amounts are integer cents. A recognition instant is Africa/Johannesburg (`docs/LOCKED_DECISIONS.md` §1; `docs/layer2/routes.md`).

## 1. Open `/staff/`

Open `http://127.0.0.1:8765/staff/`.

The page heading is “Staff session”. The form asks for person id, organisation id, a comma-separated role list, and Enigma status (`active`, `timeout`, `ambiguous`, or `suspended`). It has no email field and no password field (`docs/staff-ui/README.md`; `docs/demo/demo-script.md`, moment 1).

Enigma is not connected on this deployment. The form is the temporary staff bypass. It holds the opaque ids Enigma would have returned (`docs/LOCKED_DECISIONS.md` §15).

## 2. Submit the session

`POST /staff/session`.

A successful page has the heading “Enigma session held” and the sentence “The opaque ids and role names are held in this browser. No LMS record was written. You can continue.” Continue returns to `/staff/`, which shows the four values in the form (`docs/demo/demo-script.md`, moment 1).

The demo values are `person-test-001`, `org-test`, roles `lms.elections.write,lms.compliance.write`, and `enigma_status` `active`.

A later staff command sends `X-Enigma-Person-Id`, `X-Enigma-Organisation-Id`, `X-Enigma-Roles`, and `X-Enigma-Status` (`docs/layer2/routes.md`). A blank person id fails closed. Any status other than `active` fails closed. Timeout and an ambiguous status are HTTP 503. A missing role or a suspended enrolment is HTTP 403 (`docs/LOCKED_DECISIONS.md` §15).

## 3. Book a loan at `/exercise`

Open `GET /exercise`. The heading is “Book and pay”. The page states that a blank election is refused and that the page does not choose a rate. Until a loan exists in this process, the page says “No agreement is held in this process.”

Submit `POST /exercise/book`. The form fields are organisation id, person id, full name, identity number, service address, idempotency key, product (`micro_short_term` or `unsecured_personal`), frequency, cash advanced in cents, schedule due date, schedule amount in cents, recognised at, disbursed at, and the elections listed in section 7. The quote stub returns the rate already on the product template. It does not price the loan (`docs/demo/demo-script.md`, moment 2).

One submit quotes, books, and disburses. The servicing contract for those steps is `POST /v1/agreements` then `POST /v1/agreements/{id}/disbursements` (`docs/servicing/implementation-design.md`). The exercise screen calls both before it returns.

**Success.** Heading “Booked”. The list includes `status` `active`, `application_number` (on a fresh process, `APP-00000001`), `loan_number` (on a fresh process, `000000000001`), `credit_life_premium_cents` `199`, `frozen_full_name`, `frozen_id_number`, `agreement_id`, `organisation_id`, and `person_id` (`docs/demo/demo-script.md`, moment 2; `docs/LOCKED_DECISIONS.md` §16 and §25). Back on `/exercise`, the table shows loan number, application, agreement, status, organisation, and person.

Keep `agreement_id`. It is new on every process. The browser book and a separate Python process do not share it (`docs/demo/demo-script.md`).

## 4. Post a payment

`POST /exercise/pay`, after the loan has been booked in this same process, and after the statement run that bills the interest and service fee the receipt is meant to pay (`docs/demo/demo-script.md`, moment 4; `docs/layer3/capitalise-then-allocate.md`).

Fields: agreement id, amount in cents, due date, recognition date, and stub outcome `success` or `failure`.

**Success for `success`.** Heading “Debit-order stub”. The list includes `kind` `success`, `loan_number`, `payment_status` `allocated`, and `amount_cents`. The section 126 split is on the payment record, not on this page: due interest, then due fees, then principal (`docs/LOCKED_DECISIONS.md` §8; `docs/demo/demo-script.md`, moment 4). The worked demo receipt is 21 900 cents, split 10 000 interest, 6 900 service, 5 000 principal.

**`failure`.** The stub returns a failed receipt and does not allocate (`docs/demo/demo-script.md`, moment 4).

## 5. Issue a statement

`POST /exercise/statement`.

Fields: organisation id, person id, period start, period end, `interest_cap_present` (`true` or `false`), and VAT rate. A blank VAT rate leaves the rate unset.

**Success.** Heading “Statement stored”. The list includes `statement_id`, `pdf_sha256`, `object_key`, `organisation_id`, and `person_id`. This page does not print opening balances, the section 126 split, or the provider block. Those figures are on `Documents.issue_statement` (`docs/demo/demo-script.md`, moments 2 to 3). One statement covers one client and one credit-provider organisation (`docs/LOCKED_DECISIONS.md` §12).

The April demo period is 1–30 April 2026. Openings are 0. Closings are principal 200 000, interest 10 000, service 6 900, and 0 on the other buckets. The provider block is the compliance row, not an Enigma record (`docs/LOCKED_DECISIONS.md` §15 and §21).

## 6. Search by loan number or frozen identity number

`docs/staff-ui/README.md` does not list a search page under `/staff/`. Search is the staff route in `docs/layer2/routes.md` (statement search):

`GET /v1/staff/organisations/{organisation_id}/statements`

Send one of `loan_number` or `id_number` in the body, or the header `X-Loan-Number` or `X-Id-Number`. The call uses the same Enigma headers as the other staff routes. It accepts one of the staff write roles already named for that layer. Decision 23 does not name a separate statement-read role, so the route does not invent one (`docs/LOCKED_DECISIONS.md` §12 and §27; `docs/layer2/routes.md`).

**Success.** HTTP 200. The body copies the statement stored at issue: `statement_id`, and on each loan `loan_number`, `frozen_id_number`, and the opening and closing cents. A later receipt does not rebuild those closings.

**Fail closed.** Both keys, or neither key, returns HTTP 422 `search-key-unset`. No statement store returns HTTP 422 `statement-index-missing`. The organisation on the session must be the organisation on the path. A mismatch is HTTP 403 `mandate-denied`.

## 7. What fails closed

The page heading for a refused exercise step is “This step did not succeed”, with a code and the reason. A refused staff step uses the same heading, and the operator acknowledges it before another request is accepted (`docs/staff-ui/README.md`; `docs/COMMUNICATION.md` §2).

| Missing item | Code | What is stored |
| --- | --- | --- |
| Any book election the resolver requires (leniency, full-payment threshold, day count, in-duplum trigger, and the other elections on the book form) | `election-unset` | Nothing for that step (`docs/LOCKED_DECISIONS.md` §6 and §19; `docs/demo/demo-script.md`) |
| `interest_cap_present` blank on the statement form | `election-unset` | Nothing |
| `interest_cap_present` `false` | The reason names that no interest cap covers the value date | Nothing |
| Name, identity number, or service address blank | `identity-unset` | Nothing (`docs/LOCKED_DECISIONS.md` §16) |
| Debit outcome blank | `outcome-unset` | Success is not assumed |
| Loan number not yet issued for the agreement | `loan-number-unset` | The receipt is not applied (`docs/LOCKED_DECISIONS.md` §25) |
| Agreement id not in this process | `agreement-missing` | Nothing |
| Compliance row missing when a statement is issued on the documents path | `compliance-missing` | The statement is not stored (`docs/LOCKED_DECISIONS.md` §21; `docs/demo/demo-script.md`) |
| VAT rate missing when a service fee is levied | `vat-rate-unset` | The fee is not levied |
| Object store missing | `object-store-unset` | The brand asset and the statement artifact are not stored |
| Enigma status timeout or ambiguous | HTTP 503 | Nothing (`docs/LOCKED_DECISIONS.md` §15) |
| Enigma status suspended, or the role missing | HTTP 403 | Nothing |

A blank residual on the book form is the Decision 19 exception. The form labels it “Blank stays unset.” Resolve fills R100 (10 000 cents) when the organisation and the product are both unset. A stored value, including zero, is kept (`docs/layer2/election-schema.md`; `docs/demo/demo-script.md`).
