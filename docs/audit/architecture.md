# Technical architecture

One page for an auditor. Rules are `docs/LOCKED_DECISIONS.md`. This note does not change them.

## Layers 0–4

The tree that runs the staff demo uses this numbering. Earlier drafts used “Layer 3” for an onboarding sketch and “Layer 4” for a payment-rail sketch. On the demo tree, payment rails are Layer 3 (`docs/layer3/capitalise-then-allocate.md`).

| Layer | Owns | Source |
| --- | --- | --- |
| 0 | Calculation engine, ledger, calendar, and elections. Daily accrual, NCA caps, section 126, the in-duplum ceiling, and the account. | `docs/day1-calculation-rules.md`; `docs/ledger-implementation-note.md` |
| 1 | Statements, the Laybye parent and child, collections default and the in-duplum episode, and regulatory reads. It calls Layer 0. | `docs/statements/implementation-note.md`; `docs/laybye/implementation-note.md`; `docs/collections/implementation-note.md`; `docs/regulatory/implementation-note.md` |
| 2 | Campaigns, elections, compliance, operational ceilings, and the staff commands that write them. A campaign edit does not reprice a booked agreement. | `docs/layer2/README.md`; `docs/LOCKED_DECISIONS.md` §3 |
| 3 | Debit-order file and receipt intake. Accrue, bill what is due, levy the service fee that is due, then allocate that day’s receipts in recognition sequence. | `docs/layer3/capitalise-then-allocate.md`; `docs/layer3/receipt-intake.md`; `docs/LOCKED_DECISIONS.md` §1 and §26 |
| 4 | Statement-ready push after the monthly statement, for a consumer who is registered in Enigma. The message has no collection content. Collection notices stay with the collections system. | `docs/LOCKED_DECISIONS.md` §27; `docs/ORCHESTRATION.md` §6 |

Onboarding is the LMS capture of compliance, elections, and brand after Enigma has created the organisation (`docs/LOCKED_DECISIONS.md` §15 and §21). It is configuration, beside these layers.

## Enigma boundary

Enigma is registration, sign-on, and roles (`docs/LOCKED_DECISIONS.md` §15). The LMS stores opaque `organisation_id` and `person_id`. Compliance and brand live in the LMS: NCR number, trading name, addresses, telephone, payment-account details, brand assets, ceilings, and campaigns. Enigma does not hold them. A timeout, an ambiguous status, or a suspended enrolment fails closed.

The name, identity number, and service address frozen on the agreement come from the booking identity read (`docs/LOCKED_DECISIONS.md` §16). A later Enigma change leaves that agreement as it was frozen.

## Book, disburse, statement, payment

1. **Book.** The decision-engine stub returns the template rate, an application number (`APP-` plus eight digits), and the fixture premium. Servicing stores the agreement and freezes the three identity fields. Unset elections fail closed (`docs/demo/demo-script.md`; `docs/LOCKED_DECISIONS.md` §13, §16, and §19). The servicing route is `POST /v1/agreements` (`docs/servicing/implementation-design.md`).
2. **Disburse.** `POST /v1/agreements/{id}/disbursements` confirms disbursement. The exercise screen runs book and disburse in one submit, then `LoanNumberSeries` issues the next loan number. The sequence is not skipped (`docs/LOCKED_DECISIONS.md` §25; `docs/demo/demo-script.md`).
3. **Statement.** `Documents.issue_statement` writes one statement per client per organisation, with each loan’s opening and closing cents. The provider block is the compliance row. The exercise screen stores the artifact and returns `statement_id`, `pdf_sha256`, and `object_key` (`docs/LOCKED_DECISIONS.md` §12; `docs/demo/demo-script.md`).
4. **Payment.** The debit-file stub turns a supplied outcome into a receipt. The rail capitalises due amounts, then allocates in section 126 order. `outcome=failure` does not allocate (`docs/LOCKED_DECISIONS.md` §8 and §26; `docs/layer3/receipt-intake.md`).

## Known open sequencing gaps

The open gaps are named in `docs/testing/known-open-sequencing-gaps.md`. That note lists three tests that fail on purpose:

- `tests/test_layer0_smoke.py::test_same_day_capitalisation_is_not_applied_before_the_receipt`
- `tests/test_layer0_smoke.py::test_rejected_statement_leaves_no_interest_bill`
- `tests/test_layer1_smoke.py::test_layer1_smoke`

Decisions 1 and 8 capitalise amounts that become due that day at 00:00, then allocate a receipt recognised that day. The same-day test records that the ledger follows recognition order. The end-to-end statement path issues the statement first and posts the receipt on a later recognition date. It does not treat the current same-day order as the rule (`docs/testing/known-open-sequencing-gaps.md`).
