# Servicing that already keeps the NCA order

A multi-tenant, white-label loan management system for South African credit providers. It enforces the locked Day-1 rules on short-term, unsecured personal, and zero-cost Laybye books, and it leaves identity and sign-on in Enigma.

## Day-1 products

- **Short-term credit.** The decision engine supplies the rate, including the 5% / 3% distinction. The LMS uses that rate and checks that the calculation stays within the Act.
- **Unsecured personal loans.** The contractual rate is the client’s rate, normally the NCA maximum fixed at contract.
- **Zero-cost and Laybye.** A Laybye is the child of the loan, and the pair is one loan. Day-1 treatment is a cash deposit. Interest runs on principal minus the Laybye hold. One monthly service fee is levied, on the parent.

## What the platform already enforces

- **NCA caps.** Interest and fees charged stay within the Act. Statutory maxima sit in the calculation engine.
- **Section 126 allocation.** Due interest, then due fees, then principal. Only amounts that are already due are allocated. Excess after those amounts goes to a linked Laybye.
- **In-duplum.** The ceiling is unpaid principal at the start of the episode. The Day-1 clip is on: when charges accrued during the episode reach the ceiling, further charges stop until the episode closes. The reading follows *Nedbank v NCR* and will be adjusted if counsel names a different reading. Three section 103(5) edges remain unnamed and stay out of the implementation. The client chooses contractual breach, which fixes the ceiling, or collections default, which can close on cure.
- **One statement per client.** One statement per client per credit-provider organisation, with each loan’s own opening and closing balances. For Day-1 products the gap between statements is at most one calendar month.
- **Sequential loan numbers.** The LMS issues the loan number and links it to the application number from the decision engine. The sequence is not skipped. One application has one loan number. A Laybye keeps that core number and is distinguished by another indicator.
- **Fail-closed elections.** An unset election stores nothing. The residual write-off threshold is the exception: an unset value fills R100. A stored value, including zero, is kept. A product value overrides the organisation. The write-off is not automatic.

## White-label and Enigma

Each credit provider is a tenant, keyed by the opaque organisation id Enigma returns. The client supplies the statement header, footer, and look-and-feel. Shared templates mean one change flows through. Enigma handles registration, sign-on, passwords, and roles. The LMS stores the opaque person id and organisation id. The NCR number, trading name, addresses, telephone, payment-account details, brand assets, campaigns, and ceilings live in the LMS.

## What is included

Day-1 servicing for short-term, unsecured personal, and zero-cost Laybye books. The controls listed above. White-label statements, with the provider’s compliance block and brand assets stored in the LMS. A staff demo of six moments that runs on local stubs today.

## What is not included

A live decision engine. A live debit-order rail. Vehicle loans. Home loans.

Commercial pricing: [to be confirmed].

## Next step

Book a walkthrough. We run the six demo moments with you: staff session, quote and loan number, statement and brand, section 126 receipt, linked Laybye, and collections default.
