# External-system dummies

Thin ports so the LMS can be developed without a decision engine, a debit-order rail, collections software, or Enigma. A real adapter implements the same port. LMS call sites stay on the port and do not change when the adapter changes.

The Python ports live in `lms/ports`. The in-process dummies live in `lms/dummies`. They return fixed results and do not make network calls.

Contracts:

- [Decision engine](decision-engine.md)
- [Debit-order rail](debit-order-rail.md)
- [Collections software](collections-software.md)
- [Enigma](enigma.md)

Shared rules for these contracts:

- Money amounts are integers in cents. `25000` is R250.00. Floats and booleans are rejected.
- A recognition instant is 00:00 Africa/Johannesburg on the calendar day. A timezone-aware instant uses the Johannesburg calendar day. A naive datetime is rejected.
- The scenario (fixed success, fixed failure, fixed unmatched, silent acknowledgement) is chosen when the dummy is constructed. It is not a field on the request, so a real adapter can replace the dummy without a test switch in the payload.
- Open gaps are recorded at the end of `docs/LOCKED_DECISIONS.md`. They are not rules. The provisional field names in the contract pages are the dummy contract only.

Run the dummy tests with `python -m pytest`.
