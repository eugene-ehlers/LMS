# Receipt intake

The debit-order rail dummy queues receipts. `POST /v1/payment-rails/receipts/intake` takes that queue. `POST /v1/payment-rails/receipts` accepts the same shape from a caller, which is how a later real rail is swapped in: it implements `submit` and `take_receipts` and is passed to `PaymentRail`. Nothing in this layer opens a socket.

A receipt carries an aware recognition instant, a positive integer cent amount, an idempotency key, and optionally a purpose, loan number, ID number, agreement id, and the due date the receipt is for.

The recognition date is the Johannesburg calendar date of that instant (`value_date`). An instant that is still the previous evening in UTC and already the next morning in Johannesburg is the Johannesburg date. A naive timestamp fails closed.

## Route

1. The signed-in actor is checked with Enigma for `lms.payments.write`. The role name follows the section 19 pattern. The locked examples do not name the payment role.
2. The batch is ordered with `order_recognised_events`: value date, then recognition sequence. Sequence is the order the LMS accepted the receipt.
3. For each receipt, in that order, the rail does one of the following.

| Situation | What is posted |
| --- | --- |
| The agreement is written off | Nothing. Status `not_posted`, flag `recovery_outside_lms`. Section 8: income after a write-off is not an LMS recovery. |
| Purpose is `credit_life_premium` | Nothing on the loan ledger. Status `insurer_accepted`. Credit-life accounts stay with the insurer. There is no insurer hand-off in the lock. |
| No single agreement | Status `unapplied`. No ledger posting. |
| One agreement, purpose is the loan instalment or is omitted | Capitalise that recognition date, then `Servicing.accept_payment`, which calls `Ledger.post_payment`. |

`Servicing.accept_payment` still requires the due date the receipt is for. Omitting it fails closed. The recognition date is not used as a substitute.

An unmatched receipt is matched later with `POST /v1/payment-rails/receipts/{id}/match`. The keys are the loan number or the ID number frozen on the agreement. Exactly one agreement is allocated. Zero agreements, or more than one agreement for that ID number, leave the receipt unapplied. A loan number and an ID number that point at different agreements also leave it unapplied. The value date stays the original recognition date, and capitalisation runs for that date before `post_payment`.

## Returned unpaid

`POST /v1/payment-rails/receipts/{id}/returns`.

- After a write-off, or where nothing was posted to the loan: flag only (`returned_unpaid_after_write_off` when the agreement is written off). `Ledger.reverse` is not called. No recovery journal is posted. The balance stays as it is.
- An allocated receipt on an agreement that is not written off is reversed through `Servicing.reverse_payment`. The ledger keeps the original value date. The receipt is flagged `write_off_approval_required` so the reopened balance can be approved for write-off. This layer does not call `Collections.write_off`.

Audit rows use the seeded operational types `DEBIT_ORDER_SUBMITTED`, `LOAN_NUMBER_ISSUED`, `RECEIPT_HELD_UNAPPLIED`, `CREDIT_LIFE_PREMIUM_RECEIVED`, `RETURNED_UNPAID_FLAGGED`, and `RECOVERY_NOT_POSTED`. Those last five record actions the earlier seed did not name. They are not new locked rules. Payloads do not carry an identity number or an account number.
