# Statement-ready push payload

The LMS sends one push when the monthly statement for a client is ready. The push says the statement is available. It does not carry collection content. Collection notices stay with the collections software (locked decision 27).

This layer does not generate the statement. It reads a statement Layer 1 has already issued. On `origin/cursor/layer1-gap-closures-ccde` at `a99b1b5`, that store is `Documents.statements`, keyed by `(organisation_id, person_id, period_start, period_end)`. `Documents.issue_statement` both builds and stores a statement. This layer does not call it.

## When a push is sent

All of the following have to be true. If any check fails, nothing is sent.

1. Layer 1 already holds one statement for that client, that credit-provider organisation, and that period.
2. The statement has at least one loan. One push names every loan on that statement. There is not one push per loan. A second organisation has its own statement and its own push (locked decision 12).
3. The NCR registration number on that statement is present after trimming. A blank fails closed. An all-zero test number is sent as stored (locked decisions 21 and 27). The number is the LMS value already copied onto the statement. Enigma is not asked for it.
4. Enigma confirms the consumer is registered. The check is described in `registration-check.md`.
5. Enigma confirms the actor session. The audit record stores that person, the recognition time the caller supplied, and the statement id (locked decision 23).

A second request for the same `statement_id` returns the first receipt and does not deliver again.

The maximum period between successive Day-1 statements is one month (locked decision 12). The locked file does not define that month as a day count or a calendar boundary, and Layer 1 does not enforce it. This layer does not choose a length. It pushes a statement Layer 1 has already issued.

## Payload

`kind` is always `statement_ready`. `message` is always `Your statement is available.`

```json
{
  "kind": "statement_ready",
  "statement_id": "stmt-1",
  "organisation_id": "org-a",
  "person_id": "person-a",
  "period_start": "2026-03-01",
  "period_end": "2026-03-31",
  "ncr_registration_number": "NCRCP000000",
  "legal_name": "North Credit (Pty) Ltd",
  "message": "Your statement is available.",
  "loan_ids": ["loan-1", "loan-2"]
}
```

| Field | Source |
| --- | --- |
| `statement_id` | Issued statement |
| `organisation_id`, `person_id` | Opaque ids on the issued statement. One client, one credit-provider organisation |
| `period_start`, `period_end` | The period Layer 1 stored. Not recomputed |
| `ncr_registration_number` | LMS tenant attribute already on the statement. Required. Not read from Enigma |
| `legal_name` | LMS legal name already on the statement, so the consumer can see which provider the statement belongs to |
| `loan_ids` | Every loan on that one statement, in stored order. Opening and closing balances stay on the statement |
| `message` | Availability only |

The destination is the opaque `person_id`. The dummy push provider records that id and the payload. It does not store a telephone number or an email address, and it does not call a network.

## Left off the payload

These stay on the issued statement, or they are not LMS data. They are not copied into the push:

- Opening and closing balances, instalments, arrears, overdue amounts, fees, interest, and collection costs
- The provider telephone and payment-account details
- The consumer's contact number and email
- Any collection notice, demand, or payment instruction

A stored statement does not carry the section 21 product classification or a pure-hosting flag. This push therefore cannot see a Laybye/BNPL or pure-hosting exemption. A blank NCR number fails closed. That refusal does not decide the exemption. The gap is recorded in `docs/LOCKED_DECISIONS.md`.

## Audit

A successful first send appends one record: actor person id from Enigma, the caller's timezone-aware recognition time, action `statement_ready`, statement id, organisation id, consumer person id, and request id. A naive time fails closed. It is not moved to 00:00. Whether a notification uses the value-date rule in locked decision 1 is not stated there. No system user is invented when the actor session is missing.
