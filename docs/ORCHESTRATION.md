# LMS Orchestration Flows

Standing reference for the order in which modules are called when an event occurs.
All future agents, chats and developers must follow these flows.
If a flow is contradictory, confusing, incorrect or missing, raise it explicitly so this document can be updated.

Last updated: 2026-10-30

## Standing instruction for all agents

Before implementing or changing any event handling, booking, payment, statement, collection or write-off path:
1. Read this document and docs/LOCKED_DECISIONS.md.
2. Follow the module order for the triggered event.
3. If the flow conflicts with a locked decision, or is incomplete for the case you are handling, raise it explicitly. Do not invent a step.
4. After the change is accepted, update this document so later agents see the improved flow.

## 1. Due date arrives

Modules called (in order):
1. Ledger.accrue_day
2. Ledger.bill_interest and Ledger.levy_service_fee (capitalise due amounts)
3. Servicing.accept_payment (if a receipt has been recognised that day)
4. Collections.observe

Outcome: Capitalise then allocate. Default flag if the threshold is not met.

## 2. Receipt arrives

Modules called (in order):
1. Servicing.accept_payment
2. Ledger.post_payment

Outcome: Section 126 allocation. Excess to Laybye if linked.

## 3. Collections default flagged

Modules called (in order):
1. Collections.observe
2. Collection-campaign check (if a campaign is active for the account)

Outcome: In-duplum episode opens if the client has chosen collections default as the trigger.

## 4. Collection campaign applied

Modules called (in order):
1. Collection-campaign store
2. Ledger accrual override

Outcome: Rate or fee reduced, or instalment skipped, for the campaign period. Contractual term and instalment unchanged.

## 5. Write-off instructed

Modules called (in order):
1. Collections.write_off
2. Ledger.write_off_outstanding

Outcome: All receipts allocated first. Balance reduced to R0. If not R0, it is not a write-off.

## 6. Statement due

Modules called (in order):
1. Documents.issue_statement
2. Notifications.push (if the consumer is registered)

Outcome: One statement per client per credit-provider organisation. Push sent only if registered.

## 7. Settlement requested

Modules called (in order):
1. Ledger.quote_settlement
2. Documents.settlement_quote

Outcome: Quote binds for five business days. Early-termination charge is R0 for Day-1.

The settlement route calls those two methods in that order. It refuses the quote when the totals or the valid-until dates differ. `Ledger.quote_settlement` delegates to the calculation engine and does not keep a second formula. Five business days is section 113, through `binding_until`. The caller supplies the holiday set. No holiday calendar is assumed. A missing required election, a missing VAT rate, or a missing NCR number on a short-term or unsecured agreement fails closed. The quote does not post.

## 8. Returned unpaid after write-off

Modules called (in order):
1. Servicing.reverse_payment
2. Flag write_off_approval_required

Outcome: Flagged only. Balance not reopened. No recovery posted in the LMS.

## 9. Settlement receipt

This is not section 2. An ordinary receipt does not pay principal that is not yet due. A short receipt, a surplus, or a receipt outside the quote window is not posted on this path, and it is not turned into an ordinary payment.

Modules called (in order):
1. Ledger.accrue_day, once for each day from disbursement through the quote as-of date
2. Ledger.bill_interest, then Ledger.levy_service_fee, on each month-end in that span and on the quote as-of date
3. Ledger.post_settlement

Outcome: The receipt must equal the quoted amount in cents. Its value date must fall on or between the delivery date and valid-until. Interest is the interest in the quote. Days after the quote as-of date, and before a later receipt inside the window, are not accrued. The service fee in the settlement month is the full monthly fee. The opening month keeps the locked fraction and is not shortened to the settlement day. When the balance is R0 the agreement is marked settled. A receipt that does not match is not allocated.

Capitalise-then-allocate is Decision 1. The value date is 00:00 Africa/Johannesburg. The allocation order is Decision 8, and it includes principal that is not yet due, because this receipt is the section 125 settlement. The early-termination charge stays R0. A booked initiation amount that differs from the statutory figure in the quote fails closed. The difference is not posted. Gaps for this path are F1 to F7 in docs/OPEN_ISSUES.md.

## In-duplum flows

| Flow | Trigger | What must hold |
|------|---------|----------------|
| Contractual-breach trigger | Payment not received on due date + leniency | Ceiling fixed at unpaid principal (including pre-default capitalised initiation) on that date. Cannot be restarted. Clip stays off. |
| Collections-default trigger | Account outside limit (in arrears) | Ceiling fixed at unpaid principal when collections default starts. Cure closes the episode. Next collections default gets a fresh ceiling. |
| Cure and restart | Collections-default trigger selected, then arrears paid | Episode closes. Next collections default opens a new episode with a new ceiling. |
| Payment during episode | Receipt while in default | Reduces what is owed. Does not reset the counter for that episode. |
| Interest and fees during episode | Daily accrual | Continue. Do not stop. Count toward the ceiling only for charges that accrue during the episode. |

## Write-off flows

| Flow | Trigger | What must hold |
|------|---------|----------------|
| Residual after final instalment | Last schedule date passed, residual ≤ R100, no open in-duplum episode | Not automatic. Staff or formula instruction required. Balance reduced to R0. |
| Residual while in default | Residual remains and account is in default | Residual write-off is not used. Normal arrears and in-duplum rules continue. |
| Full write-off | Staff or external formula instruction | All receipts allocated first. Balance reduced to R0. If not R0, it is not a write-off. |
| Returned unpaid after write-off | Receipt that was included in the write-off is returned | Flagged only. Balance not reopened. No recovery posted in the LMS. |
| Recovery after write-off | New receipt after write-off | Dealt with at the accounting level, not in the LMS. |

## Open-period and frequency notes

- Service fee is pro-rata only in the opening month. Full fee thereafter, including the settlement month.
- Interest accrues daily regardless of payment frequency.
- Capitalisation occurs on due dates. Weekly or fortnightly payments do not change the monthly service-fee capitalisation.
- A payment holiday does not reset in-duplum.

## How to raise a gap

If a flow is missing, contradictory or incorrect for the case you are handling:
1. Do not invent a step.
2. Record the gap in docs/OPEN_ISSUES.md with a short description and the event that exposed it.
3. Continue only with the steps that are already locked.
