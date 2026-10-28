# Capitalise, then allocate

On a recognition date the rail posts the day's due amounts at 00:00 Africa/Johannesburg, then allocates receipts recognised that day. Allocation does not start while that capitalisation is still outstanding.

The calls are the existing ones:

1. `Ledger.accrue_day` for each day from disbursement through the recognition date, stopping at the contractual end. A day already accrued is left as it is. The day's accrual uses the balance before today's receipts, because the receipts are not posted yet.
2. When an instalment due date is on or before the recognition date, `Ledger.bill_interest` at 00:00 on the latest such due date. That debits the unbilled accrual memo. Unbilled interest is not allocatable, so a receipt before the first due date does not bill.
3. `Ledger.levy_service_fee` for the opening month once the first due date has arrived, and one full monthly fee for each later month that has a schedule due date on or before the recognition date. A month the service-fee method has already levied is left as it is. A missing VAT rate fails closed when a fee would be levied. A missing `interest_cap_present` fails closed. Neither is filled in.
4. Receipts of that value date, in recognition sequence, go to `Servicing.accept_payment` and from there to `Ledger.post_payment` and `allocate_payment`.

`allocate_payment` keeps section 126 order: due or unpaid interest, then due or unpaid fees, then principal that is due. Inside the fees the order is collection costs, default administration, credit insurance, service fee, initiation fee, and the earliest due date inside a bucket. This layer does not sort those buckets again.

Only due or unpaid amounts are allocated. Principal with a later due date is the partial-prepayment election already stored on the agreement. This layer does not choose that election.

Capitalisation and allocation can still fall on different days. A file or a receipt recognised before the instalment due date accrues and does not bill that future instalment. A receipt recognised after the due date capitalises the due date, if that has not already happened, and then allocates.

The same-day interest accrual is included in `bill_interest` because accrual runs first and the ledger bills the whole unbilled memo. The lock does not say, separately, that the accrual on the due date is itself due that day rather than at month-end. The gap is recorded. The rail does not substitute a different interest figure.

Statement issue is unchanged. One statement per client per organisation stays in Layer 1. A statement that already accrued a day or levied a month is skipped by the ledger's once-only checks. The rail does not issue a statement in order to capitalise.
