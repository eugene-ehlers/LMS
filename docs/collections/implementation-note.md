# Collections implementation note

Run on 28 October 2026, 12:22 SAST. The layer calls Layer 0. It does not re-implement calculation, allocation, or the ledger invariant.

## Stable signatures

Configuration:

```text
resolve_in_duplum_trigger(organisation: str | None, product: str | None = None) -> str
resolve_residual_threshold_cents(organisation: int | None, product: int | None = None) -> int
```

`product` wins when it is not `None`. An unset trigger raises `CalculationInputError`. A null residual at both levels returns 5 000 cents.

Ledger:

```text
Ledger.open_in_duplum_episode(*, organisation_id, loan_id, recognised_at, fall_away: bool) -> Episode
Ledger.close_in_duplum_episode(*, organisation_id, loan_id, recognised_at) -> Episode
Ledger.mark_discount_fallen_away(*, organisation_id, loan_id, recognised_at) -> None
Ledger.write_off_outstanding(*, organisation_id, loan_id, recognised_at, amount_cents: int | None = None) -> Transaction
```

`flag_default` remains for servicing. Its open path now uses the same ceiling helper. Collections does not call `flag_default`.

Authority:

```text
authorise_write_off(access, *, organisation_id, actor_id, action, amount_cents, platform, company, mandate_allowed) -> AppliedAuthority
```

Collections:

```text
Collections(servicing)
Collections.bind(agreement_id, *, in_duplum_trigger, product_in_duplum_trigger=None, residual_threshold_cents=None, product_residual_threshold_cents=None, provision_mode=None, prescription_mode=None) -> CollectionsView
Collections.observe(agreement_id, *, recognised_at) -> CollectionsView
Collections.correct_system_error(agreement_id, due_on, *, recognised_at) -> CollectionsView
Collections.receive(*, organisation_id, person_id, cents, recognised_at, idempotency_key, agreement_id, attributed_due_on) -> PaymentRecord
Collections.propose_residual_write_off(agreement_id, *, recognised_at) -> CollectionsView
Collections.write_off(agreement_id, *, recognised_at, actor_id, amount_cents, platform, company=None, mandate_allowed, access=None, action="lms.account.write_off") -> CollectionsView
Collections.record_provision(agreement_id, *, recognised_at, amount_cents=None, formula=None, promise_to_pay=None, contactability=None) -> CollectionsView
Collections.open_prescription_review(agreement_id, *, recognised_at, formula=None, promise_to_pay=None, contactability=None, signal="manual") -> CollectionsView
Collections.view(agreement_id, recognised_at=None) -> CollectionsView
```

`ProvisionFacts` carries `arrears_cents`, `recency_days`, `months_on_book`, `promise_to_pay`, `contactability`, and `as_of`. The formula callable is supplied by the client.

## How the layer calls Layer 0

Configuration. `bind` calls `resolve_in_duplum_trigger` and `resolve_residual_threshold_cents`. `observe` calls `is_full_payment` for a contractual breach and `is_in_default` for a collections default. The threshold instalment is `Servicing._threshold_instalment`. The ceiling inside `open_in_duplum_episode` is `duplum_base_cents`. Value dates go through `lms_config.calendar.value_date`. Leniency is `timedelta(days=snapshot.leniency_days)`, not the business-day helper.

Ledger. `observe` posts `open_in_duplum_episode`, `close_in_duplum_episode`, or `mark_discount_fallen_away`. Both write-off commands post `write_off_outstanding`, which debits `write_off_expense`, credits each bucket, and clears remaining slices and charges. Interest during a breach is `Ledger.accrue_day`, called by the operator, not by `observe`.

Servicing. `receive` outside prescription review is `Servicing.accept_payment`, which posts the payment and allocates. In review, the receipt is stored on `servicing.payments` with status `unapplied`, after `enigma.check(..., "payment.accept")`. Idempotency uses `Servicing._replay`, `_remember`, and `_fingerprint`. The agreement row supplies organisation, person, and `ledger_loan_id`.

This layer does not call `Ledger.flag_default`, `Servicing.morning_check`, `clip_in_duplum`, or the calculation engine's settlement quote. It does not copy engine balances onto the ledger.

## Gaps

The full list, with the lock section each one conflicts with, is in `docs/collections/layer1-draft.md`. The ones that affect callers:

- Leniency and the meaning of "not received on day X" are not split by decision 6. This code applies leniency to collections default only, and uses the full-payment threshold for both tests.
- The residual "no open episode" gate is the implementation request. Decision 8 does not state it.
- Decision 19 fills an unset residual threshold with R100. Booking fails closed if the in-duplum trigger is unset.
- The ceiling is the principal at the moment the episode is opened, not reconstructed for a check that runs after a later receipt.
- A system-error correction does not restore the discount and does not rebuild a ceiling for a breach that remains.
- Partial write-off order, prescription period, exit from review, and the write-off action id are not locked. Partial write-off is refused. No clock and no refund are posted. The action string is a caller argument.
- `Servicing.accept_payment` does not hold a prescription receipt. `Collections.receive` does.
- `Ledger.flag_default` still closes an episode from the old single morning check. Collections does not call it. Servicing still does.
- The two elections are stored on `OrganisationSettings` (and an optional product override) and copied by `resolve_customer_settings` onto the agreement. `bind` still copies them onto the collections case. `bind` before disbursement returns a view with no episode. A failed bind does not store the case. A second bind after a successful copy is `elections-frozen`. The ledger snapshot type is unchanged. An unset in-duplum trigger fails `Servicing.book` and `Ledger.book`. `bind` and `resolve_in_duplum_trigger` also fail closed.

## Test results

`PYTHONPATH=src python3 -m pytest tests/test_collections.py -q`

```text
12 passed in 0.09s
```

Pinned:

- A contractual breach is absent on the due date, present the next day, and still present after the instalment is paid. `correct_system_error` removes it. Interest still accrues on the breach day.
- A collections default opens an episode and is cured by paying the arrears. The breach remains.
- `contractual_breach` keeps one ceiling after cure and after a second missed instalment.
- `collections_default` closes on cure and opens a second episode at the new principal.
- An unset trigger fails closed on bind, on observe, and in `resolve_in_duplum_trigger`. A product override wins.
- The residual threshold defaults to 10 000 cents. Nothing is written off until `propose_residual_write_off`. A residual of R50.00 posts. R100.01 does not, and no journal is written.
- An open episode refuses the residual command.
- Prescription review stores the new receipt as `unapplied`. No payment and no refund are posted. An unset mode fails closed.
- A larger write-off over the ceiling, or without a mandate, or while Enigma times out, posts nothing. An authorised amount equal to the outstanding position posts one balanced journal.

`PYTHONPATH=src python3 -m pytest tests -q`

```text
2 failed, 129 passed, 2 skipped
```

Both failures are on `cursor/layer0-smoke-4153` before this change: `test_same_day_capitalisation_is_not_applied_before_the_receipt` and `test_rejected_statement_leaves_no_interest_bill`. Stashing this work and running those two tests fails the same way. They are not collections behaviour. See gap 15 in the design note.
