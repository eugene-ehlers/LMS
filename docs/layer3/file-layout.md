# Debit-order file layout

The LMS writes a Bankserv (ACB) collections file, the standard South African fixed-width layout published for FNB Online Banking Enterprise collections import. Real bank submission and real DebiCheck authentication are out of scope. The debit-order rail dummy accepts the file in development. A later rail replaces that object.

`PaymentRail.generate_debit_order_file` is `POST /v1/payment-rails/debit-orders`.

## When a file is produced

`debit_orders_enabled` must already be true for the organisation. A missing row fails closed. The locked decisions do not name this catalogue flag as the section 4 automation switch; the gap is recorded in `docs/LOCKED_DECISIONS.md` and is not treated as a new rule. False means collections are not automated, and no file is submitted.

The decision engine is asked for the credit-life premium on every file. `raise_collections` then builds two instructions: the loan instalment, and the credit-life premium. A missing premium fails closed. Zero is a supplied amount and does not become a Bankserv line, because that layout requires a positive amount.

The loan-line amount is the section 6 instalment still outstanding on the action date: principal still outstanding on that due date, plus levied charges that share it. Unbilled interest is not added. When the file is recognised on or after the action date, due amounts are capitalised first (see `capitalise-then-allocate.md`) so interest and the service fee that are due are included. The contractual instalment figure in section 13 is not stored on the agreement; this read does not invent one.

## LMS instruction

Every instruction, loan and credit life, carries:

| Field | Meaning |
| --- | --- |
| Loan number | 12-digit LMS number. One per application. A Laybye keeps that number and is marked `L`. The pattern is not a locked rule. |
| Amount | Integer cents of this collection. |
| Due date | Instalment action date. |
| Recognition date | Johannesburg calendar date of the instant the file was recognised. |
| Credit-life premium | Integer cents supplied by the decision engine for this run, repeated on both instructions. |

DebiCheck instructions also carry the mandate reference and an explicit tracking indicator from 0 to 10. Neither is defaulted.

## Bankserv records

Each record is 180 characters, then CRLF. The published note says 181 characters including CR and LF; the field table sums to 180. The field table is what is written.

| Record | Identifier | Role |
| --- | --- | --- |
| Installation header | `02` | First record. Remainder zero. |
| User header | `04` | Remainder zero, as in the simplified collections layout. |
| Collection | `50` | One per positive instruction. |
| Contra | `52` | One per action date. Action date `YYMMDD` at positions 59–64, so the file can be future-dated. |
| User trailer | `92` | Hash at positions 73–84. |
| Installation trailer | `94` | Last record. Remainder zero. |

Standard transaction (record `50`):

| Positions | Field | Content |
| --- | --- | --- |
| 1–2 | Identifier | `50` |
| 3–8 | User branch | Nominated-account branch from LMS compliance. Six digits. |
| 9–19 | Nominated account | Provider collection account from LMS compliance. |
| 20–23 | Filler | Zero. |
| 24–29 | Sequence | Ascending from 1. |
| 30–35 | Homing branch | Consumer branch. Six digits. |
| 36–46 | Homing account | Consumer account, or zero when the account is longer than 11 digits. |
| 47 | Account type | One digit supplied with the mandate. |
| 48–58 | Amount | Integer cents, 11 digits, no separators. |
| 59–70 | Filler and tax | Zero. |
| 71–80 | Abbreviated name | Trading name, or legal name when the trading name is blank. Longer than 10 characters fails closed. It is not truncated. |
| 81–100 | User reference | See below. |
| 101–115 | Homing name | Account name, truncated to 15 characters because that is the field width. |
| 116–130 | Filler | Zero. |
| 131–150 | Non-standard account | The homing account when it is longer than 11 digits; otherwise zero. |
| 151–180 | Filler | Zero. |

User reference, 20 characters:

- Characters 1–14: DebiCheck mandate reference, or the loan number for an EFT debit order. The layout says these characters are the mandate or agreement number. A longer reference fails closed.
- Characters 15–20, which the layout leaves free: `DO-LN ` or `DO-CL ` for an EFT loan or credit-life line, and `DC-LN ` or `DC-CL ` for DebiCheck.

Record `60` is not used. The layout calls both `50` and `60` collections and does not assign either to DebiCheck. Putting DebiCheck on `60` would invent that meaning. DebiCheck is the `DC` marker plus the mandate reference. Tracking days stay on the LMS instruction and are passed to the rail with the file. They are not written into a filler the layout says must be zero.

The trailer hash is the sum of the homing account numbers, modulo 10^12, which is the width of the 12-digit field. The layout page does not state the algorithm.

The provider branch and account come from `ComplianceStore`. Enigma is not asked for them. The consumer homing account is not an LMS field in the locked decisions. A missing debtor account, scheme, DebiCheck mandate, or tracking indicator fails closed.
