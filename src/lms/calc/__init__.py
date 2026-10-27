"""Pure day-1 calculation functions.

The public surface is the set of types and functions documented in
``docs/day1-calculation-rules.md``. Nothing here performs I/O.
"""

from lms.calc.allocation import allocate_payment
from lms.calc.examples import EXAMPLES
from lms.calc.fees import initiation_cap_ex_vat_cents, service_fee_cents
from lms.calc.interest import (
    campaign_terms,
    daily_interest_rands,
    micro_monthly_rate,
    personal_annual_rate,
)
from lms.calc.laybye import cancel_laybye, guard_s124
from lms.calc.ledger import (
    binding_until,
    execute_settlement,
    payoff_cents,
    quote_settlement,
    run,
)
from lms.calc.models import (
    Agreement,
    DayCount,
    DuplumReset,
    FeeCapBasis,
    LaybyeHold,
    ManualCharge,
    Payment,
    Policy,
    Product,
    RepoRate,
    Settlement,
    TerminalServiceFee,
    VatRate,
)
from lms.calc.money import RuleError, to_cents

__all__ = [
    "EXAMPLES",
    "Agreement",
    "DayCount",
    "DuplumReset",
    "FeeCapBasis",
    "LaybyeHold",
    "ManualCharge",
    "Payment",
    "Policy",
    "Product",
    "RepoRate",
    "RuleError",
    "Settlement",
    "TerminalServiceFee",
    "VatRate",
    "allocate_payment",
    "binding_until",
    "campaign_terms",
    "cancel_laybye",
    "daily_interest_rands",
    "execute_settlement",
    "guard_s124",
    "initiation_cap_ex_vat_cents",
    "micro_monthly_rate",
    "payoff_cents",
    "personal_annual_rate",
    "quote_settlement",
    "run",
    "service_fee_cents",
    "to_cents",
]
