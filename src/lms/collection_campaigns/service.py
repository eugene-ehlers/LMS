"""Collection campaigns on top of the Layer 0 ledger and calculators.

This module stores the campaign and calls ``Ledger.accrue_day``,
``Ledger.levy_service_fee``, ``Ledger.levy_charge``, ``Ledger.flag_default``,
``campaign_rate``, and ``apply_ex_vat_discount``. It does not keep a second
interest, day-count, VAT, or in-duplum formula.

Section 28: a campaign does not create a credit agreement. A rate or fee
reduction is for the campaign period or the rest of the term. A payment
holiday is the campaign period only. A change to the contractual term or
the contractual instalment is a restructure. This module has no operation
that writes those fields.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from lms.calc.fees import apply_ex_vat_discount
from lms.collection_campaigns.authority import AccessPort, authorise
from lms.collection_campaigns.errors import CollectionCampaignError
from lms.collection_campaigns.models import (
    FEE_TYPES,
    NOTICE_BUSINESS_DAYS,
    SCOPES,
    Application,
    Campaign,
    RegisteredAccount,
)
from lms.ledger.models import LoanAccount
from lms.ledger.service import Ledger
from lms.regulatory.audit import AuditLog
from lms_config.calendar import add_business_days, public_holidays, value_date
from lms_config.exceptions import CalculationInputError
from lms_config.locked import campaign_rate

_FEE_TYPES = frozenset(FEE_TYPES)
_SCOPES = frozenset(SCOPES)


class CollectionCampaigns:
    def __init__(self, ledger: Ledger, access: AccessPort, audit: AuditLog | None = None) -> None:
        self.ledger = ledger
        self.access = access
        self.audit = audit if audit is not None else AuditLog()
        self.campaigns: dict[str, Campaign] = {}
        self.accounts: dict[tuple[str, str], RegisteredAccount] = {}
        self.applications: dict[tuple[str, str, str], Application] = {}

    def register_account(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        product_code: str,
        contractual_fees_cents: dict[str, int],
        actor_id: str,
    ) -> RegisteredAccount:
        """Remember product and contractual fees. Does not post and does not change a campaign."""
        authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
        if not product_code or not str(product_code).strip():
            raise CollectionCampaignError(
                "product-unset",
                "The ledger stores a classification, not a product code. Registration needs the product code.",
            )
        account = self._loan(organisation_id, loan_id)
        if account.disbursement_value_date is None:
            raise CollectionCampaignError(
                "not-disbursed",
                "A collection campaign applies to a granted loan. This loan has not been disbursed.",
            )
        fees = _fees(contractual_fees_cents)
        registered = RegisteredAccount(
            organisation_id=organisation_id,
            loan_id=loan_id,
            product_code=product_code.strip(),
            contractual_fees_cents=fees,
        )
        self.accounts[(organisation_id, loan_id)] = registered
        return registered

    def create(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        start_date: date,
        end_date: date | None,
        rate_reduction: Decimal,
        rate_scope: str | None,
        fee_reductions: dict[str, int],
        fee_scope: str | None,
        payment_holiday: bool,
        notice_date: date,
        extra_holidays: frozenset[date] = frozenset(),
    ) -> Campaign:
        actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
        day = _recognition_day(recognised_at)
        reduction = _rate(rate_reduction)
        fees = _fees(fee_reductions)
        _require_bool(payment_holiday)
        _require_period(start_date, end_date)
        _require_notice(notice_date, start_date, extra_holidays)
        rate_scope, fee_scope = _durations(reduction, rate_scope, fees, fee_scope, payment_holiday)
        campaign = Campaign(
            campaign_id=str(uuid4()),
            organisation_id=organisation_id,
            start_date=start_date,
            end_date=end_date,
            rate_reduction=reduction,
            rate_scope=rate_scope,
            fee_reductions=fees,
            fee_scope=fee_scope,
            payment_holiday=payment_holiday,
            notice_date=notice_date,
            notice_business_days=NOTICE_BUSINESS_DAYS,
            created_by=actor,
            created_at=recognised_at,
        )
        self.campaigns[campaign.campaign_id] = campaign
        self._record(
            organisation_id=organisation_id,
            actor_id=actor,
            recognised_at=recognised_at,
            action="create",
            campaign_id=campaign.campaign_id,
            before=None,
            after=_campaign_json(campaign),
            loan_ids=(),
            recognition_date=day,
        )
        return campaign

    def edit(
        self,
        campaign_id: str,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        start_date: date,
        end_date: date | None,
        rate_reduction: Decimal,
        rate_scope: str | None,
        fee_reductions: dict[str, int],
        fee_scope: str | None,
        payment_holiday: bool,
        notice_date: date,
        repos: tuple = (),
        extra_holidays: frozenset[date] = frozenset(),
    ) -> Campaign:
        actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
        day = _recognition_day(recognised_at)
        campaign = self._campaign(campaign_id, organisation_id)
        reduction = _rate(rate_reduction)
        fees = _fees(fee_reductions)
        _require_bool(payment_holiday)
        _require_period(start_date, end_date)
        _require_notice(notice_date, start_date, extra_holidays)
        rate_scope, fee_scope = _durations(reduction, rate_scope, fees, fee_scope, payment_holiday)
        proposed = Campaign(
            campaign_id=campaign.campaign_id,
            organisation_id=campaign.organisation_id,
            start_date=start_date,
            end_date=end_date,
            rate_reduction=reduction,
            rate_scope=rate_scope,
            fee_reductions=fees,
            fee_scope=fee_scope,
            payment_holiday=payment_holiday,
            notice_date=notice_date,
            notice_business_days=NOTICE_BUSINESS_DAYS,
            created_by=campaign.created_by,
            created_at=campaign.created_at,
        )
        self._guard_proposed(proposed, recognised_at, repos, ignore_campaign_id=campaign.campaign_id)
        before = _campaign_json(campaign)
        campaign.start_date = proposed.start_date
        campaign.end_date = proposed.end_date
        campaign.rate_reduction = proposed.rate_reduction
        campaign.rate_scope = proposed.rate_scope
        campaign.fee_reductions = proposed.fee_reductions
        campaign.fee_scope = proposed.fee_scope
        campaign.payment_holiday = proposed.payment_holiday
        campaign.notice_date = proposed.notice_date
        self._refresh_skips(campaign, day)
        self._record(
            organisation_id=organisation_id,
            actor_id=actor,
            recognised_at=recognised_at,
            action="edit",
            campaign_id=campaign.campaign_id,
            before=before,
            after=_campaign_json(campaign),
            loan_ids=tuple(self._loan_ids(campaign.campaign_id)),
            recognition_date=day,
        )
        return campaign

    def end(
        self,
        campaign_id: str,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        end_date: date,
        repos: tuple = (),
    ) -> Campaign:
        """Set ``end_date``.

        A campaign-period reduction and a payment holiday stop after that
        date. A rest-of-term reduction continues through the contractual end
        stored on each application. A null end date is open-ended; setting
        the date is what ends it, and campaign-period values then resume.
        Decision 29: the concession goes to zero when the period ends. The
        contractual rate, fees, and instalment are not rewritten, and ending
        does not take a second section 104(2) notice.
        """
        actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
        day = _recognition_day(recognised_at)
        campaign = self._campaign(campaign_id, organisation_id)
        if not isinstance(end_date, date):
            raise CollectionCampaignError("end-date", "Ending a campaign needs an end date.")
        _require_period(campaign.start_date, end_date)
        proposed = Campaign(
            campaign_id=campaign.campaign_id,
            organisation_id=campaign.organisation_id,
            start_date=campaign.start_date,
            end_date=end_date,
            rate_reduction=campaign.rate_reduction,
            rate_scope=campaign.rate_scope,
            fee_reductions=dict(campaign.fee_reductions),
            fee_scope=campaign.fee_scope,
            payment_holiday=campaign.payment_holiday,
            notice_date=campaign.notice_date,
            notice_business_days=campaign.notice_business_days,
            created_by=campaign.created_by,
            created_at=campaign.created_at,
        )
        self._guard_proposed(proposed, recognised_at, repos, ignore_campaign_id=campaign.campaign_id)
        before = _campaign_json(campaign)
        campaign.end_date = end_date
        self._refresh_skips(campaign, day)
        self._record(
            organisation_id=organisation_id,
            actor_id=actor,
            recognised_at=recognised_at,
            action="end",
            campaign_id=campaign.campaign_id,
            before=before,
            after=_campaign_json(campaign),
            loan_ids=tuple(self._loan_ids(campaign.campaign_id)),
            recognition_date=day,
        )
        return campaign

    def apply(
        self,
        campaign_id: str,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        selector: str,
        product_code: str | None = None,
        loan_ids: tuple[str, ...] | None = None,
        repos: tuple = (),
    ) -> tuple[Application, ...]:
        """Apply one campaign to every selected account. No partial apply."""
        actor = authorise(self.access, organisation_id=organisation_id, actor_id=actor_id)
        day = _recognition_day(recognised_at)
        campaign = self._campaign(campaign_id, organisation_id)
        selected = self._select(organisation_id, selector, product_code, loan_ids)
        prepared: list[Application] = []
        for registered in selected:
            prepared.append(
                self._prepare_application(campaign, registered, actor, recognised_at, day, repos)
            )
        for application in prepared:
            self.applications[
                (application.campaign_id, application.organisation_id, application.loan_id)
            ] = application
        self._record(
            organisation_id=organisation_id,
            actor_id=actor,
            recognised_at=recognised_at,
            action="apply",
            campaign_id=campaign.campaign_id,
            before={"loans": [_before_loan(item) for item in prepared]},
            after={"loans": [_after_loan(campaign, item) for item in prepared]},
            loan_ids=tuple(item.loan_id for item in prepared),
            recognition_date=day,
        )
        return tuple(prepared)

    def periodic_rate_override(
        self,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        repos: tuple = (),
    ) -> Decimal | None:
        """Rate to pass into ``Ledger.accrue_day``.

        None when no applied rate reduction covers the day. A campaign-period
        reduction covers the campaign window. A rest-of-term reduction covers
        from the start date through the contractual end, including after the
        campaign end date. A zero reduction is not a rate change.
        """
        day = _recognition_day(recognised_at)
        application = self._application_for(organisation_id, loan_id, day, _rate_applies)
        if application is None:
            return None
        campaign = self._campaign(application.campaign_id, organisation_id)
        contractual = self.ledger.contractual_periodic_rate(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            repos=repos,
        )
        return _reduced_rate(contractual, campaign.rate_reduction)

    def accrue(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        interest_cap_present: bool,
        repos: tuple = (),
        repo_annual: Decimal | None = None,
    ):
        """Accrue one Johannesburg day through the ledger, at the campaign rate when one applies."""
        override = self.periodic_rate_override(
            organisation_id, loan_id, recognised_at, repos
        )
        return self.ledger.accrue_day(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            interest_cap_present=interest_cap_present,
            repos=repos,
            repo_annual=repo_annual,
            periodic_rate_override=override,
        )

    def service_fee_for_levy(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        monthly_cents: int,
        vat_rate: Decimal,
    ) -> int:
        """Ex-VAT cents to pass to ``Ledger.levy_service_fee``.

        The ledger prices VAT and the monthly cap. This method only subtracts
        the campaign reduction through ``apply_ex_vat_discount``.
        """
        return self._fee_cents(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            fee_type="service",
            contractual_cents=monthly_cents,
            vat_rate=vat_rate,
        )

    def levy_service_fee(self, **kwargs):
        monthly = kwargs.pop("monthly_cents")
        vat_rate = kwargs.get("vat_rate")
        reduced = self.service_fee_for_levy(
            organisation_id=kwargs["organisation_id"],
            loan_id=kwargs["loan_id"],
            recognised_at=kwargs["recognised_at"],
            monthly_cents=monthly,
            vat_rate=vat_rate if vat_rate is not None else Decimal(0),
        )
        return self.ledger.levy_service_fee(monthly_cents=reduced, **kwargs)

    def charge_cents_for_levy(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        bucket: str,
        cents: int,
    ) -> int:
        """Cents to pass to ``Ledger.levy_charge``.

        That ledger method posts no VAT of its own. The reduction uses
        ``apply_ex_vat_discount`` at a VAT rate of 0 so the floor is the
        calculator's floor and no VAT is invented here.
        """
        if bucket == "service":
            raise CollectionCampaignError(
                "bucket",
                "The monthly service fee is levied with the service-fee method.",
            )
        if bucket not in _FEE_TYPES:
            raise CollectionCampaignError("fee-type", f"{bucket} is not a collection-campaign fee type.")
        return self._fee_cents(
            organisation_id=organisation_id,
            loan_id=loan_id,
            recognised_at=recognised_at,
            fee_type=bucket,
            contractual_cents=cents,
            vat_rate=Decimal(0),
        )

    def levy_charge(self, **kwargs):
        cents = kwargs.pop("cents")
        bucket = kwargs["bucket"]
        reduced = self.charge_cents_for_levy(
            organisation_id=kwargs["organisation_id"],
            loan_id=kwargs["loan_id"],
            recognised_at=kwargs["recognised_at"],
            bucket=bucket,
            cents=cents,
        )
        return self.ledger.levy_charge(cents=reduced, **kwargs)

    def instalment_skipped(self, organisation_id: str, loan_id: str, due_on: date) -> bool:
        """True when a payment holiday on this loan skipped this contractual due date."""
        for application in self.applications.values():
            if application.organisation_id != organisation_id or application.loan_id != loan_id:
                continue
            if due_on in application.skipped_due_dates:
                return True
        return False

    def flag_default(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        check_on: date,
        due_on: date,
        instalment_cents: int,
        recognised_at: datetime,
    ) -> bool:
        """Morning check. A skipped instalment does not flag and does not close in-duplum."""
        skipped = self.instalment_skipped(organisation_id, loan_id, due_on)
        return self.ledger.flag_default(
            organisation_id=organisation_id,
            loan_id=loan_id,
            check_on=check_on,
            due_on=due_on,
            instalment_cents=instalment_cents,
            recognised_at=recognised_at,
            instalment_skipped=skipped,
        )

    def bind_collections(self, collections) -> None:
        """Collections consults this when recording a breach. It does not import collections."""
        collections.skipped_instalment = self.instalment_skipped

    def _fee_cents(
        self,
        *,
        organisation_id: str,
        loan_id: str,
        recognised_at: datetime,
        fee_type: str,
        contractual_cents: int,
        vat_rate: Decimal,
    ) -> int:
        if isinstance(contractual_cents, bool) or not isinstance(contractual_cents, int):
            raise CollectionCampaignError("fee", "A contractual fee is an integer number of cents.")
        if contractual_cents < 0:
            raise CollectionCampaignError("fee", "A contractual fee cannot be negative.")
        day = _recognition_day(recognised_at)
        application = self._application_for(organisation_id, loan_id, day, _fee_applies)
        if application is None:
            return contractual_cents
        campaign = self._campaign(application.campaign_id, organisation_id)
        if fee_type not in campaign.fee_reductions:
            return contractual_cents
        stored = application.contractual_fees_cents.get(fee_type)
        if stored is None:
            raise CollectionCampaignError(
                "fee-not-stored",
                f"The contractual {fee_type} fee was not stored when the campaign was applied.",
            )
        if stored != contractual_cents:
            raise CollectionCampaignError(
                "fee-mismatch",
                "The levy does not match the contractual fee stored for this campaign.",
            )
        reduction = campaign.fee_reductions[fee_type]
        if reduction == 0:
            return contractual_cents
        ex_vat, _vat, _total = apply_ex_vat_discount(contractual_cents, vat_rate, reduction)
        return ex_vat

    def _prepare_application(
        self,
        campaign: Campaign,
        registered: RegisteredAccount,
        actor: str,
        recognised_at: datetime,
        day: date,
        repos: tuple,
    ) -> Application:
        if (
            campaign.campaign_id,
            registered.organisation_id,
            registered.loan_id,
        ) in self.applications:
            raise CollectionCampaignError(
                "already-applied",
                "This campaign is already applied to that loan. Nothing further was applied.",
            )
        account = self._loan(registered.organisation_id, registered.loan_id)
        other = self._overlapping(
            registered.organisation_id,
            registered.loan_id,
            campaign,
            None,
            account.contractual_end,
        )
        if other is not None:
            raise CollectionCampaignError(
                "campaign-overlap",
                "Another collection campaign already covers this loan on an overlapping period. "
                "No precedence is locked, so the apply stops.",
            )
        _require_schedule(account)
        contractual = self.ledger.contractual_periodic_rate(
            organisation_id=registered.organisation_id,
            loan_id=registered.loan_id,
            recognised_at=recognised_at,
            repos=repos,
        )
        _reduced_rate(contractual, campaign.rate_reduction)
        for fee_type in campaign.fee_reductions:
            if fee_type not in registered.contractual_fees_cents:
                raise CollectionCampaignError(
                    "fee-not-stored",
                    f"The campaign reduces {fee_type}, and that contractual fee was not registered.",
                )
        instalments = _instalments(account)
        skipped = _skips_for(campaign, instalments, day, frozenset())
        return Application(
            campaign_id=campaign.campaign_id,
            organisation_id=registered.organisation_id,
            loan_id=registered.loan_id,
            contractual_base_rate=account.snapshot.base_rate,
            contractual_discount_rate=account.snapshot.discount_rate,
            contractual_periodic_rate=contractual,
            contractual_end=account.contractual_end,
            contractual_instalments=instalments,
            contractual_fees_cents=dict(registered.contractual_fees_cents),
            skipped_due_dates=skipped,
            applied_by=actor,
            applied_at=recognised_at,
        )

    def _select(
        self,
        organisation_id: str,
        selector: str,
        product_code: str | None,
        loan_ids: tuple[str, ...] | None,
    ) -> list[RegisteredAccount]:
        if selector == "organisation":
            if product_code is not None or loan_ids is not None:
                raise CollectionCampaignError(
                    "selector",
                    "An organisation apply does not also take a product or a loan list.",
                )
            chosen = [
                account
                for account in self.accounts.values()
                if account.organisation_id == organisation_id
            ]
        elif selector == "product":
            if not product_code or loan_ids is not None:
                raise CollectionCampaignError(
                    "selector",
                    "A product apply needs a product code and no loan list.",
                )
            chosen = [
                account
                for account in self.accounts.values()
                if account.organisation_id == organisation_id and account.product_code == product_code
            ]
        elif selector == "loans":
            if product_code is not None or not loan_ids:
                raise CollectionCampaignError(
                    "selector",
                    "A loan-list apply needs the list and no product code.",
                )
            if len(loan_ids) != len(set(loan_ids)):
                raise CollectionCampaignError("loan-list", "The loan list repeats an identifier.")
            chosen = []
            for loan_id in loan_ids:
                registered = self.accounts.get((organisation_id, loan_id))
                if registered is None:
                    raise CollectionCampaignError(
                        "loan-unknown",
                        f"{loan_id} is not a registered loan in this organisation. Nothing was applied.",
                    )
                chosen.append(registered)
        else:
            raise CollectionCampaignError(
                "selector-unset",
                "The apply selector is organisation, product, or loans.",
            )
        if not chosen:
            raise CollectionCampaignError(
                "no-accounts",
                "The selector matched no accounts. Nothing was applied.",
            )
        return chosen

    def _guard_proposed(
        self,
        proposed: Campaign,
        recognised_at: datetime,
        repos: tuple,
        *,
        ignore_campaign_id: str,
    ) -> None:
        for application in self._applications_of(proposed.campaign_id):
            contractual = self.ledger.contractual_periodic_rate(
                organisation_id=application.organisation_id,
                loan_id=application.loan_id,
                recognised_at=recognised_at,
                repos=repos,
            )
            _reduced_rate(contractual, proposed.rate_reduction)
            for fee_type in proposed.fee_reductions:
                if fee_type not in application.contractual_fees_cents:
                    raise CollectionCampaignError(
                        "fee-not-stored",
                        f"The campaign reduces {fee_type}, and that contractual fee was not stored.",
                    )
            other = self._overlapping(
                application.organisation_id,
                application.loan_id,
                proposed,
                ignore_campaign_id,
                application.contractual_end,
            )
            if other is not None:
                raise CollectionCampaignError(
                    "campaign-overlap",
                    "The edited period overlaps another collection campaign on the same loan. "
                    "The edit was not stored.",
                )

    def _refresh_skips(self, campaign: Campaign, today: date) -> None:
        for application in self._applications_of(campaign.campaign_id):
            application.skipped_due_dates = _skips_for(
                campaign,
                application.contractual_instalments,
                today,
                frozenset(application.skipped_due_dates),
            )

    def _overlapping(
        self,
        organisation_id: str,
        loan_id: str,
        campaign: Campaign,
        ignore_campaign_id: str | None,
        contractual_end: date,
    ) -> Campaign | None:
        for application in self.applications.values():
            if application.organisation_id != organisation_id or application.loan_id != loan_id:
                continue
            if ignore_campaign_id is not None and application.campaign_id == ignore_campaign_id:
                continue
            other = self.campaigns[application.campaign_id]
            # The loan has one contractual end. A rest-of-term reduction occupies
            # dates through that end, so a later campaign on the same loan overlaps
            # it even when the campaign windows themselves do not meet.
            end = application.contractual_end
            if _overlaps(
                campaign.start_date,
                _occupied_end(campaign, contractual_end),
                other.start_date,
                _occupied_end(other, end),
            ):
                return other
        return None

    def _application_for(
        self,
        organisation_id: str,
        loan_id: str,
        day: date,
        applies,
    ) -> Application | None:
        found: list[Application] = []
        for application in self.applications.values():
            if application.organisation_id != organisation_id or application.loan_id != loan_id:
                continue
            campaign = self.campaigns[application.campaign_id]
            if applies(campaign, day, application.contractual_end):
                found.append(application)
        if len(found) > 1:
            raise CollectionCampaignError(
                "campaign-overlap",
                "More than one collection campaign covers this recognition date. No precedence is locked.",
            )
        if not found:
            return None
        return found[0]

    def _applications_of(self, campaign_id: str) -> list[Application]:
        return [
            application
            for application in self.applications.values()
            if application.campaign_id == campaign_id
        ]

    def _loan_ids(self, campaign_id: str) -> list[str]:
        return [application.loan_id for application in self._applications_of(campaign_id)]

    def _campaign(self, campaign_id: str, organisation_id: str) -> Campaign:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None or campaign.organisation_id != organisation_id:
            raise CollectionCampaignError("campaign-unknown", "The collection campaign is not in this organisation.")
        return campaign

    def _loan(self, organisation_id: str, loan_id: str) -> LoanAccount:
        try:
            account = self.ledger.store.get(organisation_id, loan_id)
        except Exception as exc:
            code = getattr(exc, "code", "")
            if code == "not-found":
                raise CollectionCampaignError(
                    "loan-unknown",
                    "The loan is not in this organisation.",
                ) from exc
            raise
        if account.instrument_kind != "loan":
            raise CollectionCampaignError(
                "not-a-loan",
                "A collection campaign applies to the loan, not to the Laybye child.",
            )
        return account

    def _record(
        self,
        *,
        organisation_id: str,
        actor_id: str,
        recognised_at: datetime,
        action: str,
        campaign_id: str,
        before: dict | None,
        after: dict,
        loan_ids: tuple[str, ...],
        recognition_date: date,
    ) -> None:
        self.audit.append(
            organisation_id=organisation_id,
            occurred_at=recognised_at,
            event_type="COLLECTION_CAMPAIGN_CHANGED",
            category="operational",
            enigma_person_id=actor_id,
            payload={
                "action": action,
                "campaign_id": campaign_id,
                "actor_id": actor_id,
                "recognition_date": recognition_date.isoformat(),
                "loan_ids": list(loan_ids),
                "before": before,
                "after": after,
            },
        )


def _recognition_day(recognised_at: datetime) -> date:
    if recognised_at.tzinfo is None:
        raise CollectionCampaignError(
            "timestamp-naive",
            "Decision 1: a timestamp must carry a zone so the Johannesburg recognition date is known.",
        )
    return value_date(recognised_at)


def _rate(value: Decimal) -> Decimal:
    if isinstance(value, float) or isinstance(value, bool) or not isinstance(value, Decimal):
        raise CollectionCampaignError("rate", "A rate reduction is a Decimal. A float is not accepted.")
    if value < 0:
        raise CollectionCampaignError(
            "rate-increase",
            "A collection campaign reduces the rate or leaves it unchanged. It does not increase it.",
        )
    return value


def _fees(raw: dict[str, int]) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise CollectionCampaignError("fee", "Fee reductions are a map of fee type to integer cents.")
    cleaned: dict[str, int] = {}
    for fee_type, cents in raw.items():
        if fee_type not in _FEE_TYPES:
            raise CollectionCampaignError("fee-type", f"{fee_type} is not a collection-campaign fee type.")
        if isinstance(cents, bool) or not isinstance(cents, int):
            raise CollectionCampaignError("fee", "A fee reduction is an integer number of cents.")
        if cents < 0:
            raise CollectionCampaignError(
                "fee-increase",
                "A collection campaign reduces a fee or leaves it unchanged. It does not increase it.",
            )
        cleaned[fee_type] = cents
    return cleaned


def _require_bool(value: bool) -> None:
    if not isinstance(value, bool):
        raise CollectionCampaignError("payment-holiday", "The payment-holiday flag is required.")


def _require_period(start_date: date, end_date: date | None) -> None:
    if not isinstance(start_date, date):
        raise CollectionCampaignError("start-date", "A collection campaign needs a start date.")
    if end_date is not None and not isinstance(end_date, date):
        raise CollectionCampaignError("end-date", "The end date is a date or open-ended.")
    if end_date is not None and end_date < start_date:
        raise CollectionCampaignError("period", "The end date precedes the start date.")


def _require_notice(notice_date: date, start_date: date, extra_holidays: frozenset[date]) -> None:
    if not isinstance(notice_date, date):
        raise CollectionCampaignError("notice-date", "The LMS stores the section 104(2) notice date.")
    earliest = earliest_effective(notice_date, extra_holidays)
    if start_date < earliest:
        raise CollectionCampaignError(
            "notice-short",
            "Section 104(2) requires written notice of at least five business days "
            "before the change takes effect. The start date is inside that interval.",
        )


def earliest_effective(notice_date: date, extra_holidays: frozenset[date] = frozenset()) -> date:
    """First Johannesburg date on which the change may take effect.

    ``add_business_days`` is section 2(5): the notice date is excluded and the
    returned day is included. Public holidays are the statutory set from
    ``lms_config.calendar``. One-off declarations are ``extra_holidays``.
    """
    horizon = notice_date + timedelta(days=40)
    holidays = set(extra_holidays)
    for year in range(notice_date.year, horizon.year + 1):
        for holiday, _name, _source in public_holidays(year):
            holidays.add(holiday)
    return add_business_days(notice_date, NOTICE_BUSINESS_DAYS, frozenset(holidays))


def _reduced_rate(contractual: Decimal, reduction: Decimal) -> Decimal:
    """Subtract the collection reduction using the ledger's ``campaign_rate``.

    ``discount_fallen_away`` stays false. That flag belongs to the origination
    discount already reflected in ``contractual``. Passing it here would drop
    the collection reduction. A reduction above the contractual rate is refused
    by ``campaign_rate``; this function does not floor it.
    """
    try:
        return campaign_rate(contractual, reduction)
    except CalculationInputError as exc:
        raise CollectionCampaignError(
            "rate-above-contract",
            "The collection-campaign reduction is above the contractual rate on this "
            "recognition date. campaign_rate refuses that pair. The net is not floored here.",
        ) from exc


def _durations(
    rate_reduction: Decimal,
    rate_scope: str | None,
    fee_reductions: dict[str, int],
    fee_scope: str | None,
    payment_holiday: bool,
) -> tuple[str | None, str | None]:
    """Section 28: each reduction says whether it lasts for the campaign or the term.

    A missing duration is not defaulted. A duration with no reduction is refused.
    A campaign with no rate reduction, fee reduction, or payment holiday is refused.
    """
    for name, scope in (("rate_scope", rate_scope), ("fee_scope", fee_scope)):
        if scope is not None and scope not in _SCOPES:
            raise CollectionCampaignError(
                "scope",
                f"{name} is campaign_period or rest_of_term.",
            )
    rate_reduced = rate_reduction > 0
    fee_reduced = any(cents > 0 for cents in fee_reductions.values())
    if rate_reduced and rate_scope is None:
        raise CollectionCampaignError(
            "scope-unset",
            "A rate reduction is for the campaign period or the rest of the term. "
            "The duration was not given.",
        )
    if fee_reduced and fee_scope is None:
        raise CollectionCampaignError(
            "scope-unset",
            "A fee reduction is for the campaign period or the rest of the term. "
            "The duration was not given.",
        )
    if not rate_reduced and rate_scope is not None:
        raise CollectionCampaignError(
            "scope-unused",
            "A rate duration is stored only when the rate is reduced.",
        )
    if not fee_reduced and fee_scope is not None:
        raise CollectionCampaignError(
            "scope-unused",
            "A fee duration is stored only when a fee is reduced.",
        )
    if not rate_reduced and not fee_reduced and not payment_holiday:
        raise CollectionCampaignError(
            "change-unset",
            "A collection campaign needs one or more of a rate reduction, a fee reduction, "
            "or a payment holiday.",
        )
    return rate_scope, fee_scope


def _covers(campaign: Campaign, day: date) -> bool:
    if day < campaign.start_date:
        return False
    if campaign.end_date is not None and day > campaign.end_date:
        return False
    return True


def _rate_applies(campaign: Campaign, day: date, contractual_end: date) -> bool:
    if campaign.rate_reduction <= 0 or campaign.rate_scope is None:
        return False
    return _scoped(campaign, day, campaign.rate_scope, contractual_end)


def _fee_applies(campaign: Campaign, day: date, contractual_end: date) -> bool:
    if campaign.fee_scope is None or not any(cents > 0 for cents in campaign.fee_reductions.values()):
        return False
    return _scoped(campaign, day, campaign.fee_scope, contractual_end)


def _scoped(campaign: Campaign, day: date, scope: str, contractual_end: date) -> bool:
    if day < campaign.start_date:
        return False
    if scope == "rest_of_term":
        return day <= contractual_end
    return _covers(campaign, day)


def _occupied_end(campaign: Campaign, contractual_end: date) -> date | None:
    """Last recognition date the campaign occupies on this loan.

    None means a campaign-period effect is open-ended. A rest-of-term
    reduction occupies dates through the contractual end, including after
    ``end_date``. A payment holiday occupies only the campaign window.
    """
    ends: list[date] = []

    def occupy(active: bool, scope: str | None) -> bool:
        if not active:
            return False
        if scope == "rest_of_term":
            ends.append(contractual_end)
            return False
        if campaign.end_date is None:
            return True
        ends.append(campaign.end_date)
        return False

    if occupy(campaign.rate_reduction > 0, campaign.rate_scope):
        return None
    if occupy(any(cents > 0 for cents in campaign.fee_reductions.values()), campaign.fee_scope):
        return None
    if occupy(campaign.payment_holiday, "campaign_period"):
        return None
    if not ends:
        return campaign.end_date
    return max(ends)


def _overlaps(
    start_a: date,
    end_a: date | None,
    start_b: date,
    end_b: date | None,
) -> bool:
    if end_a is not None and start_b > end_a:
        return False
    if end_b is not None and start_a > end_b:
        return False
    return True


def _instalments(account: LoanAccount) -> tuple[tuple[date, int], ...]:
    if account.schedule_versions:
        return tuple(account.schedule_versions[-1].lines)
    return tuple((slice_.due_on, slice_.amount_cents) for slice_ in account.slices)


def _skips_for(
    campaign: Campaign,
    instalments: tuple[tuple[date, int], ...],
    today: date,
    previous: frozenset[date],
) -> tuple[date, ...]:
    kept: list[date] = []
    for due, _amount in instalments:
        if due < today:
            if due in previous:
                kept.append(due)
            continue
        if campaign.payment_holiday and _covers(campaign, due):
            kept.append(due)
    return tuple(kept)


def _require_schedule(account: LoanAccount) -> None:
    """The contractual instalment is copied. A missing schedule fails closed."""
    if not _instalments(account):
        raise CollectionCampaignError(
            "schedule-unset",
            "The contractual instalment is not on the loan. The campaign was not applied.",
        )


def _money(value: Decimal) -> str:
    return format(value, "f")


def _campaign_json(campaign: Campaign) -> dict:
    return {
        "campaign_id": campaign.campaign_id,
        "organisation_id": campaign.organisation_id,
        "start_date": campaign.start_date.isoformat(),
        "end_date": None if campaign.end_date is None else campaign.end_date.isoformat(),
        "rate_reduction": _money(campaign.rate_reduction),
        "rate_scope": campaign.rate_scope,
        "fee_reductions_cents": dict(campaign.fee_reductions),
        "fee_scope": campaign.fee_scope,
        "payment_holiday": campaign.payment_holiday,
        "notice_date": campaign.notice_date.isoformat(),
        "notice_business_days": campaign.notice_business_days,
        "open_ended": campaign.end_date is None,
    }


def _instalment_json(instalments: tuple[tuple[date, int], ...]) -> list:
    return [[due.isoformat(), amount] for due, amount in instalments]


def _before_loan(application: Application) -> dict:
    return {
        "loan_id": application.loan_id,
        "periodic_rate": _money(application.contractual_periodic_rate),
        "base_rate": _money(application.contractual_base_rate),
        "discount_rate": _money(application.contractual_discount_rate),
        "fees_cents": dict(application.contractual_fees_cents),
        "instalments": _instalment_json(application.contractual_instalments),
        "contractual_end": application.contractual_end.isoformat(),
    }


def _after_loan(campaign: Campaign, application: Application) -> dict:
    contractual = application.contractual_periodic_rate
    effective = _reduced_rate(contractual, campaign.rate_reduction)
    return {
        "loan_id": application.loan_id,
        "periodic_rate": _money(contractual),
        "effective_rate": _money(effective),
        "fees_cents": dict(application.contractual_fees_cents),
        "fee_reductions_cents": {
            fee_type: campaign.fee_reductions[fee_type]
            for fee_type in application.contractual_fees_cents
            if fee_type in campaign.fee_reductions
        },
        "instalments": _instalment_json(application.contractual_instalments),
        "contractual_end": application.contractual_end.isoformat(),
        "payment_holiday": campaign.payment_holiday,
        "rate_scope": campaign.rate_scope,
        "fee_scope": campaign.fee_scope,
        "skipped_due_dates": [due.isoformat() for due in application.skipped_due_dates],
    }
