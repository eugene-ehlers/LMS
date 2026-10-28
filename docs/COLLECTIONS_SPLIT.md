# LMS and Automated Collections Split

Standing decision. The LMS produces collection files. A separate system executes collections.

Last updated: 2026-10-28

## Rules

- The LMS produces the daily collection file. It does not execute the collection.
- The collection file contains the contractual instalment and the credit-life premium amount for each account that is due on that day.
- Customers may select any day of the month for payment. Different clients may select different days for interest and fee capitalisation.
- A separate collections system consumes the LMS collection file. That system may add:
  - Ad-hoc payments generated during the collection process.
  - Promise-to-pay amounts.
  - Additional credit-life collections if required.
- The collections system returns receipts (matched or unmatched) to the LMS. The LMS capitalises due amounts first, then allocates the receipt.
- The LMS does not store collection-process state (promise-to-pay adherence, contactability, or ad-hoc collection decisions). Those remain in the collections system.
- The LMS does not send collection notices. Collection notices remain the responsibility of the collections software.

## Standing instruction for all agents

Before implementing any collection-file generation or receipt intake:
1. Read this document and docs/LOCKED_DECISIONS.md.
2. The LMS produces the file and receives the receipt. It does not decide what to collect beyond the contractual instalment and the credit-life premium.
3. If a path requires the LMS to store collection-process state, raise it explicitly. Do not add that state to the LMS.
