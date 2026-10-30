# Statements and documents — implementation note

Code: `src/lms/statements` and `lms_config.compliance`. SQL shape: `db/migrations/0005_statement_compliance.sql`. Tests use the in-memory store. This note does not change `docs/LOCKED_DECISIONS.md`.

## Stable signatures

```text
Documents(servicing: Servicing, compliance: ComplianceStore)

Documents.issue_statement(
    *,
    organisation_id: str,
    person_id: str,
    period_start: date,
    period_end: date,
    interest_cap_present: bool,
    vat_rate: Decimal | None = None,
    receipts: tuple[RecognisedReceipt, ...] = (),
) -> StoredStatement

Documents.enquire(
    *,
    organisation_id: str,
    person_id: str,
    loan_id: str,
    request_on: date,
    holidays: frozenset[date],
    interest_cap_present: bool,
    period_start: date | None = None,
    period_end: date | None = None,
    vat_rate: Decimal | None = None,
) -> AmountOwing

Documents.settlement_quote(
    *,
    agreement_id: str,
    as_of: date,
    delivered_on: date,
    request_on: date,
    holidays: frozenset[date],
    vat_rate: Decimal | None = None,
) -> StoredQuote

RecognisedReceipt(
    agreement_id: str,
    cents: int,
    recognised_at: datetime,
    attributed_due_on: date,
    idempotency_key: str,
)

ProviderCompliance(
    organisation_id, legal_name, ncr_registration_number, trading_name,
    physical_address, postal_address, telephone,
    bank_name, bank_account_number, branch_code, payment_reference,
)
ComplianceStore.put(record: ProviderCompliance) -> None
ComplianceStore.require(organisation_id: str) -> ProviderCompliance
```

`interest_cap_present` has no default. `holidays=None` raises `holidays-unset`. A repeat of the same statement period returns the stored statement and does not fold again. A repeat of the same quote key returns the stored quote and does not post.

## Calls into Ledger, Configuration, and Servicing

Statement issue, per disbursed agreement, for each Johannesburg date from the later of `period_start` and disbursement through the earlier of `period_end` and contractual end:

1. `Servicing.enigma.check` before any document (`statement.issue`, `statement.enquire`, `settlement.quote`). Timeout, ambiguous status, and suspended enrolment fail closed (§15).
2. `ComplianceStore.require` copies legal name, NCR number, trading name, addresses, telephone, and payment-account details. Enigma is not called for those fields.
3. On the flag date only (`due_on + leniency_days` from the booking snapshot): `Servicing.morning_check`. Not on other days. `Ledger.flag_default` is not called directly.
4. `Ledger.accrue_day`. `already-accrued` and `outside-term` are ignored on a replay. Other ledger errors propagate.
5. On `month_end` only: `Ledger.bill_interest`, then `Ledger.levy_service_fee`. Opening-month fraction only when the first due date is after disbursement and the month is the disbursement month. `TerminalServiceFee.PRO_RATA` is not passed (§9). A service-fee month with `vat_rate is None` raises `vat-rate-unset` before any of that day's posts.
6. Receipts whose Johannesburg value date is that day are passed to `Servicing.accept_payment` after step 5, in `recognised_at` order. That is the capitalise-then-allocate order (§1, §8). `Servicing.issue_statement` is not called. It bills unbilled interest at every `period_end`.
7. Opening buckets are the previous stored closing for that loan (§12). The first statement has no previous closing. Its opening is `Ledger.bucket_balance` as of the day before `period_start`, labelled `no-previous-statement` (G2). If a later opening disagrees with the ledger as of the day before `period_start`, the run raises `opening-chain`. No section 112 line is written.
8. `Ledger.issue_statement` is then called as the period-uniqueness guard. The document is frozen, including a SHA-256 of `b"PDF-STUB\n"` plus canonical JSON. That is not a PDF.

Rates on the section come from the booking snapshot: `campaign_rate` and `nominal_annual_rate(periodic, periods_per_year(product))` (§3, §17, §19). Both nominals are labelled. `annual_rate_cell` stays `None` (G16). Instalment cents are the next principal slice plus ex-VAT and VAT of charges that share that due date, excluding `additional_monthly` (§6). Unbilled interest is not included.

Section 110 `enquire` folds from disbursement through `request_on` with no receipts and does not call `Ledger.issue_statement`. `deliver_by` is `add_business_days` for 10 business days, or 20 when `period_start` is before the calendar anniversary of `request_on`. That anniversary reading of "one year" is not a locked rule.

Section 113 `settlement_quote` builds an engine `Agreement` from the snapshot and calls `quote_settlement`. It refuses a non-zero `early_termination_cents` (`early-termination-unexpected`) and checks `valid_until == binding_until(delivered_on, holidays)`. `deliver_by` is five business days after `request_on`. It does not call `execute_settlement` and does not call `early_termination_ceiling_cents`. The policy helpers `_day_count`, `_repo_fall`, and `_prepayment` are the ledger's private snapshot readers, used so the quote uses the booked election. A public mapper is not added here.

## Conflict with locked decision 15

§15 says Enigma owns organisations and the LMS stores only opaque ids. The statements task says legal name, NCR number, trading name, addresses, telephone, and payment-account details are read from LMS configuration, not from Enigma. `cfg_provider_compliance` is that configuration. `LOCKED_DECISIONS.md` is not edited. Consumer name, identity number, and service address stay the values frozen on the loan (§16).

## Remaining gaps

Raised, not solved. Detail is in `docs/statements/layer1-design.md` section 9.

- G1. No single section 109 rand total. Per-bucket opening and closing are stored.
- G2. First opening is the ledger the day before `period_start`. That is not locked.
- G3. Capitalisation follows the engine: month-end and settlement, not every statement date that is not a month-end.
- G4. `arrears_cents` is `None`. Unpaid items with a due date before the statement date are listed and not summed.
- G5. Billed interest and the interest memo are both stored. No single "interest accrued" cell.
- G6. A reversal inside a stored period has no section 112 line.
- G7. Section 108 frequency is not enforced.
- G8. `statement_date` is `period_end`.
- G9. Receipts already posted before this run are not reversed or reallocated.
- G10. Section 110(4) excuses are not applied. The enquiry still returns figures.
- G11. The compliance row exists because the task named LMS configuration. §15 does not name it.
- G12. Zero-cost and lay-by sections sit on the same document. No separate form is chosen.
- G13. Contact and payment fields are on the compliance row. They are not a locked election (§19).
- G14. Loans with different frozen names are not refused. No name is selected for the document.
- G15. The printed address is the frozen service address.
- G16. The single annual-rate cell stays empty.
- G17. `fees_levied_cents` sums initiation, service, and additional monthly. Membership of "fees levied" is not locked. `legal_fees_cents` is `None`.
- G18. No logo is read from `cfg_brand`.
- G19. Intermediate and large agreements are not given a different form. The quote path refuses anything other than short-term or unsecured.
- G20. No section 104 notice.
- G21. `morning_check` sees posted payments only. An unposted flag-date receipt is not previewed. A cure between flag dates has no ledger call that only closes the episode.

Collections, regulatory extracts, and lay-by claim logic are not in this layer.

## Test results

`python3 -m pytest tests/test_statements.py -q` — 10 passed.

Pinned:

- April opening equals the stored March closing.
- A 1 cent receipt recognised on 31 March is allocated after that day's interest bill. Principal stays R1 000.00. A second issue of the same period returns the same statement id and PDF hash.
- One statement per person per organisation. An overlapping period raises `statement-exists`.
- Legal name and NCR number on the statement are the compliance row after the Enigma stub name is changed. The frozen consumer name is unchanged.
- A missing compliance row raises `compliance-missing`. A blank required field is refused by `ComplianceStore.put`.
- A missing VAT rate raises `vat-rate-unset` and leaves only the booking transaction.

`python3 -m pytest tests -q` — 127 passed, 2 skipped, 2 failed. The two failures are in `tests/test_layer0_smoke.py`. They use `Servicing.issue_statement`, which this layer does not call.

- `test_same_day_capitalisation_is_not_applied_before_the_receipt` ends in `pytest.fail`. It records that the servicing statement path does not capitalise 1 May before a 1 May receipt, and that the two bullets in §1 do not settle whether that day's interest is due that day.
- `test_rejected_statement_leaves_no_interest_bill` shows that path bills interest before it rejects a missing VAT rate.

Those two are left as they are. Changing them would be a Layer 0 change, and the first test says it does not choose a rule.
