# LMS Orchestration Flows

Standing reference for the order in which modules are called when an event occurs.
All future agents, chats and developers must follow these flows.
If a flow is contradictory, confusing, incorrect or missing, raise it explicitly so this document can be updated.

Last updated: 2026-10-28

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

## 8. Returned unpaid after write-off

Modules called (in order):
1. Servicing.reverse_payment
2. Flag write_off_approval_required

Outcome: Flagged only. Balance not reopened. No recovery posted in the LMS.

## 9. Restructure requested

A restructure changes the contractual term or the contractual instalment. It is not a collection campaign, an early settlement, or a settlement re-advance.

This flow was missing. The steps below are the restructure instruction and Decisions 13, 16, 19, and 23. No other step is included.

Modules called (in order):
1. Client consent is checked. The consent flag and the consent date are stored. Missing consent fails closed.
2. Required elections are checked. A missing election fails closed. The elections that pass are frozen on the new agreement.
3. Identity fields (name, ID number, service address) are frozen on the new agreement.
4. The decision engine supplies the new rate, term, and instalment. The LMS stores those values. It does not re-decide concurrent, subsequent, or restructure rules.
5. A new agreement is created and linked to the original.
6. The original agreement is marked restructured. Its balance, in integer cents, is transferred to the new agreement.
7. The new contractual instalment is stored.
8. The outcome is returned (success with a confirmation, or failure with a specific reason) and written to the audit log.

Outcome: New agreement linked to the original. Original marked restructured. Balance transferred. Contractual instalment stored.

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
