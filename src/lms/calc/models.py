"""Data the calculation engine accepts. Party and organisation identity is an Enigma id."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from lms.calc.money import RuleError


class Product(StrEnum):
    MICRO = "micro"  # NCA short-term credit transaction
    PERSONAL = "personal"  # NCA unsecured credit transaction
    LAYBYE_BNPL = "laybye_bnpl"  # zero-cost CPA lay-by / zero-charge payment plan
    LAYBYE_SECURITY = "laybye_security"  # zero-interest hold applied to a micro loan


class FeeCapBasis(StrEnum):
    """Whether the prescribed rand caps are exclusive or inclusive of VAT."""

    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"


class TerminalServiceFee(StrEnum):
    """Service fee for a calendar month in which the agreement ends after the commencement month."""

    FULL = "full"  # lawful maximum after MFSA v NCR (Davis J, 14 August 2020)
    PRO_RATA = "pro_rata"  # stricter product policy


class DuplumReset(StrEnum):
    """How a later default interacts with cost of credit that accrued in an earlier default."""

    FRESH = "fresh"  # statutory text: amounts that accrue during this default
    AGGREGATE = "aggregate"  # NCR draft guideline, GN 54 of 2015 (not a regulation)


class DayCount(StrEnum):
    """Provider day-count. Actual/actual is the recommendation for new products."""

    ACTUAL = "actual"  # actual days in the month, and 365 or 366 in the year
    FIXED = "fixed"  # regulation 40's 30-day month and 365-day year; not 30/360
    THIRTY_360 = "thirty_360"  # standard 30/360: 30-day months, 360-day year


class RepoFallChoice(StrEnum):
    """LOCKED_DECISIONS §11. There is no platform default."""

    CONTRACT_RATE_CONTINUES = "contract_rate_continues"
    LOWER_OF_CONTRACT_AND_CAP = "lower_of_contract_and_cap"


class PrepaymentChoice(StrEnum):
    """LOCKED_DECISIONS §13. There is no platform default."""

    SHORTEN_TERM = "shorten_term"  # reduce the latest unpaid slices
    DROP_INSTALMENT = "drop_instalment"  # reduce the earliest unpaid slices


# Prescribed maxima. Sources are cited in docs/day1-calculation-rules.md.
SHORT_TERM_FIRST_MONTHLY = Decimal("0.05")
SHORT_TERM_SUBSEQUENT_MONTHLY = Decimal("0.03")
UNSECURED_MAX_MARGIN = Decimal("0.21")
INITIATION_FLAT_CENTS = 16_500  # R165
INITIATION_THRESHOLD_CENTS = 100_000  # R1,000
INITIATION_PERCENT = Decimal("0.10")
INITIATION_RAND_CAP_CENTS = 105_000  # R1,050
INITIATION_PRINCIPAL_PERCENT = Decimal("0.15")
SERVICE_FEE_MONTHLY_CAP_CENTS = 6_000  # R60
SHORT_TERM_MAX_ADVANCE_CENTS = 800_000  # R8,000
SMALL_AGREEMENT_MAX_CENTS = 1_500_000  # R15,000
LARGE_AGREEMENT_MIN_CENTS = 25_000_000  # R250,000
LAYBYE_MAX_PENALTY_RATE = Decimal("0.01")


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def agreement_size(principal_cents: int, *, mortgage: bool = False) -> str:
    """NCA s 9 read with the thresholds in GN 713 of 1 June 2006.

    Those rand thresholds are confirmed by current commentary and were not found
    to have been replaced. See decision D-THRESHOLD in the rules document.
    """
    if mortgage or principal_cents >= LARGE_AGREEMENT_MIN_CENTS:
        return "large"
    if principal_cents <= SMALL_AGREEMENT_MAX_CENTS:
        return "small"
    return "intermediate"


@dataclass(frozen=True)
class Policy:
    """Day-1 product policy. Unset leniency, threshold, and repo-fall fail closed."""

    fee_cap_basis: FeeCapBasis = FeeCapBasis.EXCLUSIVE
    terminal_service_fee: TerminalServiceFee = TerminalServiceFee.FULL
    duplum_reset: DuplumReset = DuplumReset.FRESH
    day_count: DayCount = DayCount.ACTUAL
    interest_on_deferred_initiation: bool = False
    service_fee_monthly_cents: int = SERVICE_FEE_MONTHLY_CAP_CENTS
    vat_registered: bool = True
    count_vat_in_duplum: bool = True
    # §6: no numeric default. None fails closed when a day is folded.
    leniency_days: int | None = None
    full_payment_threshold_percent: Decimal | None = None
    # §11: no platform default.
    repo_fall: RepoFallChoice | None = None
    # §13 and §19: no platform default. Required only when a payment would
    # reduce principal that is not yet due.
    prepayment_choice: PrepaymentChoice | None = None

    def __post_init__(self) -> None:
        if self.service_fee_monthly_cents < 0:
            raise RuleError("policy", "Service fee cannot be negative.")
        if self.service_fee_monthly_cents > SERVICE_FEE_MONTHLY_CAP_CENTS:
            raise RuleError(
                "service-fee-cap",
                "Monthly service fee exceeds the prescribed R60 cap.",
            )
        if self.leniency_days is not None and (
            type(self.leniency_days) is not int or self.leniency_days < 0
        ):
            raise RuleError("leniency", "Leniency days must be a non-negative integer.")
        if self.full_payment_threshold_percent is not None:
            threshold = Decimal(self.full_payment_threshold_percent)
            if threshold < 0 or threshold > 100:
                raise RuleError(
                    "threshold",
                    "Full-payment threshold must be between 0 and 100 percent.",
                )
            object.__setattr__(self, "full_payment_threshold_percent", threshold)


@dataclass(frozen=True)
class RepoRate:
    """SARB policy rate (still the NCA 'reference rate' / repurchase rate), effective on ``effective_from``."""

    effective_from: date
    annual_rate: Decimal

    def __post_init__(self) -> None:
        if self.annual_rate < 0:
            raise RuleError("repo", "Repo rate cannot be negative.")


@dataclass(frozen=True)
class VatRate:
    effective_from: date
    rate: Decimal

    def __post_init__(self) -> None:
        if self.rate < 0:
            raise RuleError("vat", "VAT rate cannot be negative.")


@dataclass(frozen=True)
class Agreement:
    """One enrolled credit agreement. Enigma owns the party, organisation, and enrolment records."""

    product: Product
    credit_provider_org_id: str
    consumer_party_id: str
    product_enrolment_id: str
    cash_advanced_cents: int
    advance_date: date
    maturity_date: date
    # PERSONAL: fixed margin over repo. Clipped to 21 percentage points.
    margin_annual: Decimal = UNSECURED_MAX_MARGIN
    # MICRO: None means "charge the prescribed 5% or 3%". A lower agreed rate is allowed.
    agreed_monthly_rate: Decimal | None = None
    # Other short-term inception dates for this consumer at this credit provider.
    # Do not include this agreement. A same-day other loan counts as earlier.
    prior_short_term_inceptions: tuple[date, ...] = ()
    initiation_paid_upfront: bool = False
    # Optional explicit principal slices. They must sum to the cash advanced.
    # If empty, the whole principal falls due on maturity.
    principal_instalments: tuple[tuple[date, int], ...] = ()
    cash_to_consumer: bool = True
    mortgage: bool = False
    # Linked lay-by. Interest uses principal minus this hold. The lay-by is not a second fee.
    linked_laybye_id: str | None = None
    laybye_hold_cents: int = 0
    # Campaign: contractual base rate minus this discount. The unit matches the product
    # (monthly points on micro, annual points on personal). Fee discounts are cents off
    # the ex-VAT fee the agreement would otherwise charge.
    campaign_interest_discount: Decimal = Decimal("0")
    campaign_initiation_discount_cents: int = 0
    campaign_service_discount_cents: int = 0
    campaign_falls_away_on_default: bool = False
    # §2: short-term and unsecured default to non-capitalised. True is the
    # caller's statement that this product may capitalise. The engine does not
    # keep a section 102 product list.
    initiation_capitalised: bool = False
    # Decision 2. None means this agreement was not booked, and a settlement
    # quote still prices the statutory initiation formula. An integer, including
    # zero, is the booked ex-VAT fee and replaces that formula.
    booked_initiation_ex_vat_cents: int | None = None
    # The principal slices already contain the booked ex-VAT fee. The quote
    # does not add that fee again. VAT on it is still part of the settlement.
    initiation_already_in_principal: bool = False

    def __post_init__(self) -> None:
        if not self.credit_provider_org_id or not self.consumer_party_id:
            raise RuleError("enigma", "Credit provider and consumer ids are required.")
        if not self.product_enrolment_id:
            raise RuleError("enigma", "Product enrolment id is required.")
        if self.cash_advanced_cents <= 0:
            raise RuleError("principal", "Cash advanced must be positive.")
        if self.maturity_date < self.advance_date:
            raise RuleError("term", "Maturity cannot precede the advance date.")
        if self.product == Product.MICRO:
            self._validate_micro()
            # Fail at construction if the agreed rate is above the 5% / 3% cap.
            _ = self.monthly_rate
        elif self.product == Product.PERSONAL:
            self._validate_personal()
        elif self.product in (Product.LAYBYE_BNPL, Product.LAYBYE_SECURITY):
            raise RuleError(
                "product",
                "Lay-by plans are not interest-bearing agreements. Use the lay-by functions.",
            )
        if self.booked_initiation_ex_vat_cents is not None and self.booked_initiation_ex_vat_cents < 0:
            raise RuleError("initiation", "The booked initiation fee cannot be negative.")
        if self.initiation_already_in_principal and (
            not self.initiation_capitalised or self.booked_initiation_ex_vat_cents is None
        ):
            raise RuleError(
                "initiation",
                "A capitalised initiation fee already in the loan value needs the booked fee.",
            )
        slices = self.resolved_instalments()
        expected = self.cash_advanced_cents
        if self.initiation_already_in_principal:
            expected += self.booked_initiation_ex_vat_cents or 0
        if sum(amount for _, amount in slices) != expected:
            raise RuleError("instalments", "Principal instalments must sum to the cash advanced.")
        for due_on, amount in slices:
            if amount <= 0:
                raise RuleError("instalments", "Each principal instalment must be positive.")
            if due_on < self.advance_date or due_on > self.maturity_date:
                raise RuleError("instalments", "Instalment due date is outside the agreement term.")
        if self.laybye_hold_cents < 0:
            raise RuleError("laybye", "Lay-by hold cannot be negative.")
        if self.laybye_hold_cents > 0 and not self.linked_laybye_id:
            raise RuleError(
                "laybye-link",
                "A lay-by hold needs the linked lay-by id. The LMS does not invent the parent/child link.",
            )
        if self.campaign_interest_discount < 0:
            raise RuleError("campaign", "Campaign interest discount cannot be negative.")
        if self.campaign_initiation_discount_cents < 0 or self.campaign_service_discount_cents < 0:
            raise RuleError("campaign", "Campaign fee discount cannot be negative.")

    def _validate_micro(self) -> None:
        # Reg 39(2): short-term is a cash disbursement of at most R8,000, repayable within 6 months,
        # and not paid to a related person or to someone other than the consumer.
        if not self.cash_to_consumer:
            raise RuleError(
                "short-term-payee",
                "Reg 39(2) excludes a short-term classification when the advance is not disbursed to the consumer.",
            )
        if self.cash_advanced_cents > SHORT_TERM_MAX_ADVANCE_CENTS:
            raise RuleError(
                "short-term-amount",
                "Deferred amount exceeds R8,000. Do not price this agreement as a short-term transaction.",
            )
        if self.maturity_date > add_months(self.advance_date, 6):
            raise RuleError(
                "short-term-term",
                "Term exceeds 6 months. Do not price this agreement as a short-term transaction.",
            )
        if self.agreed_monthly_rate is not None and self.agreed_monthly_rate < 0:
            raise RuleError("rate", "Monthly rate cannot be negative.")

    def _validate_personal(self) -> None:
        if self.mortgage:
            raise RuleError("product", "Day-1 personal loans are unsecured.")
        if self.margin_annual < 0:
            raise RuleError("rate", "Margin cannot be negative.")
        if self.margin_annual > UNSECURED_MAX_MARGIN:
            raise RuleError(
                "unsecured-margin",
                "Margin exceeds the prescribed RR + 21% maximum for an unsecured credit transaction.",
            )
        if agreement_size(self.cash_advanced_cents) == "large":
            raise RuleError(
                "day1-large",
                "Day-1 personal loans stay below R250,000 so the s 125(2)(c) early-termination charge does not arise.",
            )

    def resolved_instalments(self) -> tuple[tuple[date, int], ...]:
        if self.principal_instalments:
            return tuple(sorted(self.principal_instalments))
        return ((self.maturity_date, self.cash_advanced_cents),)

    @property
    def monthly_rate(self) -> Decimal:
        if self.product != Product.MICRO:
            raise RuleError("rate", "Monthly short-term rate is only defined for micro agreements.")
        cap = micro_cap(self.advance_date, self.prior_short_term_inceptions)
        if self.agreed_monthly_rate is None:
            return cap
        if self.agreed_monthly_rate > cap:
            raise RuleError(
                "short-term-rate",
                f"Agreed monthly rate {self.agreed_monthly_rate} exceeds the prescribed {cap}.",
            )
        return self.agreed_monthly_rate


def micro_cap(advance_date: date, prior_inceptions: tuple[date, ...]) -> Decimal:
    """5% on the first short-term loan of the calendar year, otherwise 3%.

    ``prior_inceptions`` are other loans. A prior loan on the same date counts as earlier,
    so the later same-day agreement is a subsequent loan.
    """
    same_year_prior = any(
        prior.year == advance_date.year and prior <= advance_date for prior in prior_inceptions
    )
    if same_year_prior:
        return SHORT_TERM_SUBSEQUENT_MONTHLY
    return SHORT_TERM_FIRST_MONTHLY


@dataclass(frozen=True)
class Payment:
    on: date
    cents: int
    # ``initiation_upfront`` is applied to the initiation fee ahead of same-day interest.
    purpose: str = "ordinary"
    source: str = "consumer"  # consumer | laybye_security
    # Recognition order when several receipts share a calendar day (§1).
    sequence: int = 0

    def __post_init__(self) -> None:
        if self.cents <= 0:
            raise RuleError("payment", "Payment must be positive.")
        if self.purpose not in ("ordinary", "initiation_upfront"):
            raise RuleError("payment", f"Unknown payment purpose {self.purpose}.")


@dataclass(frozen=True)
class ManualCharge:
    """Default administration, collection, or credit-insurance premium supplied by the caller.

    The engine does not invent the Magistrates' Court letter tariff or a premium table.
    It clips the charge to the in-duplum room when the agreement is in default.
    """

    on: date
    kind: str  # default_admin | collection | insurance
    total_cents: int
    ex_vat_cents: int | None = None
    vat_cents: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("default_admin", "collection", "insurance"):
            raise RuleError("charge", f"Manual charge kind {self.kind} is not a s 101(1)(e)-(g) bucket.")
        if self.total_cents < 0:
            raise RuleError("charge", "Manual charge cannot be negative.")


@dataclass(frozen=True)
class Settlement:
    """Pay the s 113 quote. Handled by ``run`` / ``execute_settlement``."""

    paid_on: date
    cents: int
    as_of: date
    delivered_on: date
    valid_until: date

    def __post_init__(self) -> None:
        if self.cents <= 0:
            raise RuleError("settlement", "Settlement payment must be positive.")


@dataclass(frozen=True)
class LaybyeHold:
    """Replace the linked lay-by hold at 00:00 on ``on``.

    The value is the hold balance, not a delta. Interest that day uses this balance.
    """

    on: date
    hold_cents: int

    def __post_init__(self) -> None:
        if self.hold_cents < 0:
            raise RuleError("laybye", "Lay-by hold cannot be negative.")


Event = Payment | ManualCharge | Settlement | LaybyeHold


@dataclass(frozen=True)
class Charge:
    charge_id: str
    kind: str
    levied_on: date
    due_on: date
    ex_vat_cents: int
    vat_cents: int
    amount_cents: int
    remaining_cents: int
    duplum_episode: int | None
    sequence: int


@dataclass(frozen=True)
class PrincipalSlice:
    due_on: date
    amount_cents: int
    remaining_cents: int
    sequence: int


@dataclass(frozen=True)
class DuplumEpisode:
    episode_no: int
    started_on: date
    ceiling_cents: int
    accrued_cents: int
    closed_on: date | None


@dataclass(frozen=True)
class Clip:
    on: date
    kind: str
    requested_cents: int
    charged_cents: int
    reason: str


@dataclass(frozen=True)
class State:
    as_of: date | None
    status: str  # open | settled
    principal_slices: tuple[PrincipalSlice, ...]
    charges: tuple[Charge, ...]
    unbilled_ordinary: Decimal
    unbilled_duplum: Decimal
    unbilled_duplum_episode: int | None
    # Cents of unbilled duplum interest already added to the episode at a mid-month close.
    duplum_interest_counted_cents: int
    episodes: tuple[DuplumEpisode, ...]
    in_default: bool
    next_sequence: int
    next_episode_no: int
    prior_duplum_accrued_cents: int
    service_months_levied: tuple[tuple[int, int], ...]
    initiation_levied: bool
    suspense_cents: int
    clips: tuple[Clip, ...]
    waived_cents: int
    settled_on: date | None
    laybye_hold_cents: int = 0
    # False once a campaign that falls away on default has been switched off.
    # A later cure does not turn it back on. That restoration is not in the locked decisions.
    campaign_discount_active: bool = True

    @property
    def principal_cents(self) -> int:
        return sum(slice_.remaining_cents for slice_ in self.principal_slices)
