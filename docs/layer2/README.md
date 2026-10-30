# Layer 2 — campaigns, elections, and staff commands

Staff with an Enigma role create and edit campaigns, elections, compliance details, and operational rand ceilings. The routes are in [routes](routes.md). The election fields are in [election-schema](election-schema.md). Places where the current lock and the existing calculation code do not say the same thing are in [gaps](gaps.md), and the undecided points are at the end of `docs/LOCKED_DECISIONS.md`.

This layer calls the existing configuration and calculation interfaces:

| Need | Call |
| --- | --- |
| Net rate while the discount does not exceed the base | `lms_config.locked.campaign_rate` |
| In-duplum trigger | `lms_config.locked.resolve_in_duplum_trigger` |
| Fee discount that must not go below R0 | `lms.calc.fees.apply_ex_vat_discount` |
| Johannesburg recognition date | `lms_config.calendar.value_date` |
| Compliance row | `lms_config.compliance.ComplianceStore` |
| Audit row | `lms.regulatory.audit.AuditLog` |

It does not re-implement those functions. A campaign edit or end writes the campaign row and an audit row. It does not update `lms.decision_intake`, the ledger, or a statement.

Amounts are integer cents. Rates are decimal fractions. A missing election fails closed on resolve. A missing compliance field fails closed in the existing compliance store. The NCR number is compulsory, and a test number of all zeros is a present number.
