# Staff demo script

A staff member can run this on the local process or on the container. Both serve the same screens. Start a new process for each run so the first application number is `APP-00000001` and the first loan number is `000000000001`.

Local:

```bash
PYTHONPATH=src python3 -m lms.staff_ui
```

Open `http://127.0.0.1:8765/staff/`.

Container: the process listens on `0.0.0.0:8765`. Open `http://<host>:8765/staff/`. When `LMS_REQUIRE_DEPLOY_CONFIG=1`, the process exits before the screens start unless the database settings and `LMS_S3_BUCKET` in the checklist are present.

Moments 2 to 6 share one Python process, because the HTML pages do not print opening balances, the section 126 split, Laybye interest, or the in-duplum flag. Run them from the repository root with `PYTHONPATH=src`. The same field values can be typed into `/exercise`. That browser booking is a different process and has its own agreement id.

Amounts are integer cents. Instants are Africa/Johannesburg.

## Checklist

These rows must be present before the demo. A missing row fails closed and stores nothing for that step. The organisation-settings table stays empty: the book form supplies the elections, and a blank field is not filled in.

| Row | Value for this demo | Missing row |
| --- | --- | --- |
| `product_code` | `micro_short_term` | `election-unset`. No product is assumed. |
| `leniency_days` | `3` | `election-unset` |
| `full_payment_threshold_percent` | `100` | `election-unset` |
| `interest_on_deferred_initiation` | `none` | `election-unset` |
| `repo_rate_fall` | `contract_rate` | `election-unset` |
| `day_count_code` | `actual_actual` | `election-unset` |
| `vat_on_rand_maxima` | `exclusive` | `election-unset` |
| `late_disbursement` | `keep_instalment` | `election-unset` |
| `partial_prepayment` | `shorten_term` | `election-unset` |
| `in_duplum_trigger` | `collections_default` | `election-unset` on book. `trigger-unset` on `Collections.bind`. |
| Identity | `Test Consumer`, `0000000000000`, `1 Dummy Street, Johannesburg` | `identity-unset` |
| `interest_cap_present` | `true` | Blank is `election-unset`. `false` raises “no interest cap covers the value date” and stores nothing. |
| `vat_rate` | `0.15` | `vat-rate-unset` when a service fee is levied. |
| Compliance row for `org-test` | Legal name, NCR number, addresses, telephone, bank name, account, branch, payment reference. Trading name may be an empty string and must still be present. | `compliance-missing`. The statement is not stored. |
| Object store | `MemoryStore` in the Python process, or `LMS_S3_BUCKET` on the container | `object-store-unset`. The brand asset and the HTTP statement artifact are not stored. |
| Debit outcome | `success` | `outcome-unset`. Success is not assumed. |
| Loan number | Issued at disbursement in this process | `loan-number-unset`. The receipt is not applied. |
| Laybye child | Opened by `prepare_pair` before the receipt | `laybye-missing`. The receipt is not posted. |
| Deploy settings, only when `LMS_REQUIRE_DEPLOY_CONFIG=1` | `LMS_DB_HOST`, `LMS_DB_NAME`, `LMS_DB_USER`, `LMS_DB_PASSWORD`, `LMS_S3_BUCKET`, and at least one `lms.ref_credit_classification` row | The process exits, or the reference check fails. |

`residual_write_off_threshold_cents` may be left blank. An unset value fills 10_000 cents. A stored value, including zero, is kept.

Use the test NCR number `0000000000`. Use the synthetic identity above. Do not use a live decision engine, a live debit rail, or a production identity.

## 1. Staff session

**Call:** `GET /staff/`, then `POST /staff/session`.

**Values:**

- `person_id`: `person-test-001`
- `organisation_id`: `org-test`
- `roles`: `lms.elections.write,lms.compliance.write`
- `enigma_status`: `active`

**Success:** the response heading is “Enigma session held”, with the sentence “The opaque ids and role names are held in this browser. No LMS record was written. You can continue.” `GET /staff/` then shows those four values in the form.

**Stub:** Enigma is not connected. This form is the temporary staff bypass. It collects no email address and no password.

## 2. Quote, book, and loan number

**Screen:** `GET /exercise`, then `POST /exercise/book`.

**Function:** `Exercise.book` after `DecisionQuoteStub.quote` and `book_quoted`. The loan number is `LoanNumberSeries.issue`.

```python
from lms.exercise import Exercise
from lms.objects import MemoryStore

exercise = Exercise(objects=MemoryStore())
booked = exercise.book({
    "organisation_id": "org-test",
    "person_id": "person-test-001",
    "full_name": "Test Consumer",
    "id_number": "0000000000000",
    "service_address": "1 Dummy Street, Johannesburg",
    "idempotency_key": "book-demo-1",
    "product_code": "micro_short_term",
    "frequency": "monthly",
    "cash_advanced_cents": "200000",
    "due_on": "2026-05-01",
    "schedule_amount_cents": "200000",
    "recognised_at": "2026-04-01T08:00:00+02:00",
    "disbursed_at": "2026-04-01T10:00:00+02:00",
    "leniency_days": "3",
    "full_payment_threshold_percent": "100",
    "interest_on_deferred_initiation": "none",
    "repo_rate_fall": "contract_rate",
    "day_count_code": "actual_actual",
    "vat_on_rand_maxima": "exclusive",
    "late_disbursement": "keep_instalment",
    "partial_prepayment": "shorten_term",
    "in_duplum_trigger": "collections_default",
})
```

Leave `residual_write_off_threshold_cents` off the form.

**Success:** `status` is `active`, `application_number` is `APP-00000001`, `loan_number` is `000000000001`, `credit_life_premium_cents` is `199`, `frozen_full_name` is `Test Consumer`, and `frozen_id_number` is `0000000000000`. Keep `agreement_id` from this response. It is a new id on every process.

The browser list shows the same application number, loan number, status, organisation, and person. Its agreement id belongs to the server process.

**Stub:** `DecisionQuoteStub` returns the 5% monthly rate already on the `micro_short_term` template, the application number, and the fixture premium of 199 cents. It does not price the loan and it does not call an external engine. `EnigmaStub` freezes the name, identity number, and address from the form.

## 3. Statement, balances, and brand header and footer

**Screen:** `POST /exercise/statement` and `POST /exercise/brand`. The statement screen returns `statement_id`, `pdf_sha256`, and `object_key`. The balances and the provider block are on `Documents.issue_statement`.

**Function:** `ComplianceStore.put`, then `Documents.issue_statement`, then `Exercise.store_brand`.

```python
from datetime import date
from decimal import Decimal
from lms.statements.service import Documents
from lms_config.compliance import ComplianceStore, ProviderCompliance

compliance = ComplianceStore()
compliance.put(ProviderCompliance(
    organisation_id="org-test",
    legal_name="Test Credit Provider",
    ncr_registration_number="0000000000",
    trading_name="Test Credit",
    physical_address="2 Dummy Street, Johannesburg",
    postal_address="PO Box 1, Johannesburg",
    telephone="0100000000",
    bank_name="Test Bank",
    bank_account_number="0000000000",
    branch_code="000000",
    payment_reference="org-test",
))
documents = Documents(exercise.servicing, compliance)
april = documents.issue_statement(
    organisation_id="org-test",
    person_id="person-test-001",
    period_start=date(2026, 4, 1),
    period_end=date(2026, 4, 30),
    interest_cap_present=True,
    vat_rate=Decimal("0.15"),
)
header = exercise.store_brand({
    "organisation_id": "org-test",
    "asset_name": "statement-header",
    "body": "Test Credit header",
})
footer = exercise.store_brand({
    "organisation_id": "org-test",
    "asset_name": "statement-footer",
    "body": "Test Credit footer",
})
```

**Success:** `april.loans[0].opening_source` is `no-previous-statement`. Opening balances are 0 for every bucket. Closing balances are principal `200000`, interest `10000`, service `6900`, and 0 for initiation, credit insurance, default administration, collection costs, additional monthly, and laybye hold.

The stored statement carries the header block `Test Credit Provider`, trading name `Test Credit`, NCR `0000000000`, `2 Dummy Street, Johannesburg`, `PO Box 1, Johannesburg`, telephone `0100000000`. The payment block on that statement is `Test Bank`, account `0000000000`, branch `000000`, reference `org-test`.

`header["object_key"]` is `brand/org-test/statement-header` and `footer["object_key"]` is `brand/org-test/statement-footer`. Read those two objects back: the bodies are `Test Credit header` and `Test Credit footer`.

**Stub:** the statement body is the issuer’s stored payload. `store_brand` writes the header and footer into the object store. Neither call leaves the machine.

## 4. Debit-order receipt and the updated statement

**Screen:** `POST /exercise/pay` with the `agreement_id` from moment 2.

**Function:** `Exercise.pay`, which builds one `DebitOrderFile` and calls `DebitFileStub.acknowledge` and `apply_debit_receipts`. The split is `PaymentRecord.allocations` on `exercise.servicing.payments`. Then `Documents.issue_statement` for 1 May.

```python
paid = exercise.pay({
    "agreement_id": booked["agreement_id"],
    "amount_cents": "21900",
    "due_on": "2026-05-01",
    "recognition_date": "2026-05-01",
    "outcome": "success",
})
allocations = exercise.servicing.payments[paid["payment_id"]].allocations
may = documents.issue_statement(
    organisation_id="org-test",
    person_id="person-test-001",
    period_start=date(2026, 5, 1),
    period_end=date(2026, 5, 1),
    interest_cap_present=True,
    vat_rate=Decimal("0.15"),
)
```

**Success:** the screen and `paid` show `kind` `success`, `loan_number` `000000000001`, `payment_status` `allocated`, and `amount_cents` `21900`.

`allocations` is `(("interest", 10000), ("service", 6900), ("principal", 5000))`. That is the section 126 order for the amounts due on this loan: interest, then the service fee, then principal. The three amounts add to 21_900 cents.

`may.loans[0].opening_source` is `previous-closing`, and that opening equals the April closing. The May closing is principal `195000`, interest `0`, service `0`, and 0 on the other buckets.

Run this receipt after the April statement. The April run is what bills the interest and the service fee that this receipt pays.

**Stub:** `DebitFileStub` turns the one instruction into a success receipt. `outcome=failure` returns a failed receipt and does not allocate.

## 5. Linked Laybye, net interest, and one service fee

This moment uses a new `Ledger`. A pre-disbursement receipt on the loan from moment 2 is refused with `already-granted`, because that loan is already disbursed. There is no `/exercise` route for this moment.

**Functions:** `prepare_pair`, `receive_pre_disbursement`, `grant_loan`, `accrue_parent`, `levy_parent_service_fee`.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from lms.laybye import (
    accrue_parent,
    grant_loan,
    levy_parent_service_fee,
    prepare_pair,
    receive_pre_disbursement,
)
from lms.ledger.service import Ledger
from lms_config.locked import OrganisationSettings
from lms_config.templates import micro_short_term

johannesburg = ZoneInfo("Africa/Johannesburg")
laybye_ledger = Ledger()
laybye_settings = OrganisationSettings(
    leniency_days=0,
    full_payment_threshold_percent=Decimal("100"),
    interest_on_deferred_initiation="none",
    repo_rate_fall="contract_rate",
    day_count_code="actual_actual",
    vat_on_rand_maxima="exclusive",
    late_disbursement="keep_instalment",
    partial_prepayment="shorten_term",
    in_duplum_trigger="collections_default",
)
parent, child = prepare_pair(
    laybye_ledger,
    organisation_id="org-test",
    person_id="person-test-001",
    product=micro_short_term(),
    organisation=laybye_settings,
    recognised_at=datetime(2026, 3, 1, 8, 0, tzinfo=johannesburg),
    cash_advanced_cents=100_000,
    frequency="monthly",
    schedule=((date(2026, 12, 15), 100_000),),
    identity_name="Test Consumer",
    identity_number="0000000000000",
    service_address="1 Dummy Street, Johannesburg",
    quoted_disbursement=date(2026, 4, 1),
)
receipt = receive_pre_disbursement(
    laybye_ledger,
    organisation_id="org-test",
    parent_loan_id=parent.loan_id,
    cents=40_000,
    recognised_at=datetime(2026, 3, 10, 11, 0, tzinfo=johannesburg),
)
grant_loan(
    laybye_ledger,
    organisation_id="org-test",
    parent_loan_id=parent.loan_id,
    recognised_at=datetime(2026, 4, 1, 8, 0, tzinfo=johannesburg),
    schedule=((date(2026, 12, 15), 100_000),),
)
accrual = accrue_parent(
    laybye_ledger,
    organisation_id="org-test",
    parent_loan_id=parent.loan_id,
    recognised_at=datetime(2026, 4, 2, 8, 0, tzinfo=johannesburg),
    interest_cap_present=True,
)
fee = levy_parent_service_fee(
    laybye_ledger,
    organisation_id="org-test",
    loan_id=parent.loan_id,
    recognised_at=datetime(2026, 4, 1, 9, 0, tzinfo=johannesburg),
    monthly_cents=6_000,
    due_on=date(2026, 12, 15),
    interest_cap_present=True,
    vat_rate=Decimal("0.15"),
    vat_registered=True,
    opening=True,
    first_due=date(2026, 12, 15),
)
```

**Success:** `receipt.kind` is `laybye_deposit` and `receipt.value_date` is `2026-03-10`. The child `laybye_hold` is `40000` cents and the parent principal is `0` before `grant_loan`.

After the grant and `accrue_parent`: `principal_cents` is `100000`, `hold_cents` is `40000`, `base_cents` is `60000`, and `day_rands` is `1.0000000000`. Interest for that day uses the net base of 60_000 cents. Principal on the parent stays `100000`.

`fee.kind` is `service_fee`. The parent service bucket is `6900` cents and the child service bucket is `0`. One fee is levied, on the parent. A second `levy_parent_service_fee` in April raises `service-fee-once` and posts nothing.

**Stub:** none. These calls stay on the ledger.

## 6. Collections default, ceiling, and the clip

Continue the process from moments 2 to 4. The in-duplum trigger on that agreement is `collections_default`.

**Function:** `Collections.bind`, then `Collections.observe`, then `Ledger.in_duplum_clip_status` and `Ledger.clip_in_duplum`.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from lms.collections.service import Collections
from lms_config.locked import IN_DUPLUM_CLIP_POSTS

johannesburg = ZoneInfo("Africa/Johannesburg")
loan_id = exercise.servicing.agreements[booked["agreement_id"]].ledger_loan_id
collections = Collections(exercise.servicing)
collections.bind(booked["agreement_id"], in_duplum_trigger="collections_default")
flagged = collections.observe(
    booked["agreement_id"],
    recognised_at=datetime(2026, 5, 5, 8, 0, tzinfo=johannesburg),
)
clip = exercise.servicing.ledger.in_duplum_clip_status("org-test", loan_id)
before_clip = len(exercise.servicing.ledger.store.transactions_for("org-test", loan_id))
exercise.servicing.ledger.clip_in_duplum()
after_clip = len(exercise.servicing.ledger.store.transactions_for("org-test", loan_id))
```

**Success:** `flagged.collections_default` is `True`. `flagged.open_episode_ceiling` is `195000` cents, the unpaid principal when this episode opens. `flagged.contractual_breaches` is `(date(2026, 5, 1),)` and `flagged.episode_count` is `1`.

`IN_DUPLUM_CLIP_POSTS` is `True`. `clip["episode_no"]` is `1`, `clip["ceiling_cents"]` is `195000`, and `clip["accrued_cents"]` is `0`. `clip["in_duplum_ceiling_reached"]` is `False` and `clip["warning"]` is `None`. `after_clip` equals `before_clip`: `clip_in_duplum()` adds no transaction while accrued charges during the episode are below the ceiling. The clip stays off on this run. `observe` itself records the default with one `default_flag` transaction.

**Stub:** none. `observe` reads the ledger and posts no receipt.
