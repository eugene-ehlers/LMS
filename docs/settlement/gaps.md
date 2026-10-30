# Early settlement gaps

These are raised, not locked. The rows live in `docs/OPEN_ISSUES.md`. Decision 2 and Decision 19 were updated for the booked initiation fee, the residual default, and the booking trigger.

The copy of the locked decisions on `main` is a stub that points at `/tmp/locked_updated.md`. That file is not in the tree. This path follows the restored text already on `cursor/merged-smoke-ccde`.

| ID | What this path does |
|----|---------------------|
| S1 | Closed. `Ledger.quote_settlement` delegates to the calculation engine. Documents calls that method. |
| S2 | Closed. The quote uses the booked initiation fee. A capitalised fee is not added again. A fee that is not capitalised has its outstanding portion added, and VAT is included. Execute posts that VAT when the ledger charge does not yet hold it. |
| S3 | Open and unchanged. The ordinary receipt path was not reordered. |
| F1 | Five business days stays orchestration plus section 113. |
| F2 | Interest stays at the quote as-of date inside the window. |
| F3 | A surplus is refused. It is not sent to a Laybye. |
| F4 | An open in-duplum episode is not closed by this receipt. |
| F5 | A quote with repo rows is refused. |
| F6 | A naive timestamp and an unknown agreement id are not audited. |
| F7 | If the engine's per-bill interest rounding and the ledger's cumulative memo differ by one cent, the receipt is refused. No balancing journal is posted. The 1 March to 10 April 2026 sample matched. |

C7 is closed. Booking refuses a missing in-duplum trigger.

The capitalised-initiation principal reduction order is still unset. The existing ledger guard fails closed. This path does not add a reduction order.

Public holidays are only the set the caller supplies. `public_holidays()` is not applied on its own.
