"""Staff commands for campaigns, elections, compliance, and ceilings.

Every change appends an audit row: the Enigma person id, the timestamp,
and the before and after values. Campaign edits do not load or rewrite
decision-intake rows. Statement generation is not called.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from lms.regulatory.audit import AuditLog
from lms.staff.authority import (
    ROLE_CAMPAIGN_WRITE,
    ROLE_CEILING_COMPANY_WRITE,
    ROLE_CEILING_PLATFORM_WRITE,
    ROLE_COMPLIANCE_WRITE,
    ROLE_ELECTIONS_WRITE,
    StaffActor,
    require_actor,
    require_role,
)
from lms.staff.campaigns import Campaign, CampaignStore, build_campaign, end_campaign
from lms.staff.ceilings import (
    COMPANY,
    CURRENCY,
    PLATFORM,
    AppliedCeiling,
    CeilingStore,
    RandCeiling,
    tighter,
)
from lms.staff.elections import ElectionStore, ElectionValues
from lms.staff.errors import StaffError
from lms.staff.intake import DecisionIntake, IntakeStore, record_intake
from lms.staff.rates import fee_after_discount, integer_cents
from lms_config.calendar import value_date
from lms_config.compliance import ComplianceStore, ProviderCompliance


class StaffOffice:
    def __init__(
        self,
        *,
        campaigns: CampaignStore | None = None,
        elections: ElectionStore | None = None,
        ceilings: CeilingStore | None = None,
        compliance: ComplianceStore | None = None,
        intakes: IntakeStore | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.campaigns = campaigns or CampaignStore()
        self.elections = elections or ElectionStore()
        self.ceilings = ceilings or CeilingStore()
        self.compliance = compliance or ComplianceStore()
        self.intakes = intakes or IntakeStore()
        self.audit = audit or AuditLog()

    def create_campaign(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        *,
        product_id: str | None,
        start_date: date,
        end_date: date,
        base_rate: Decimal,
        discount_rate: Decimal,
        fall_away_choice: str,
        fall_away_trigger: str | None,
        initiation_fee_discount_cents: int,
        service_fee_discount_cents: int,
    ) -> Campaign:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        campaign = build_campaign(
            organisation_id=actor.organisation_id,
            product_id=product_id,
            start_date=start_date,
            end_date=end_date,
            base_rate=base_rate,
            discount_rate=discount_rate,
            fall_away_choice=fall_away_choice,
            fall_away_trigger=fall_away_trigger,
            initiation_fee_discount_cents=initiation_fee_discount_cents,
            service_fee_discount_cents=service_fee_discount_cents,
        )
        self.campaigns.add(campaign)
        self._audit(actor, recognised_at, "CAMPAIGN_CREATED", before=None, after=_campaign_payload(campaign))
        return campaign

    def edit_campaign(
        self,
        actor: StaffActor,
        campaign_id: str,
        recognised_at: datetime,
        *,
        product_id: str | None,
        start_date: date,
        end_date: date,
        base_rate: Decimal,
        discount_rate: Decimal,
        fall_away_choice: str,
        fall_away_trigger: str | None,
        initiation_fee_discount_cents: int,
        service_fee_discount_cents: int,
    ) -> Campaign:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        current = self._own_campaign(actor, campaign_id)
        edited = build_campaign(
            organisation_id=current.organisation_id,
            product_id=product_id,
            start_date=start_date,
            end_date=end_date,
            base_rate=base_rate,
            discount_rate=discount_rate,
            fall_away_choice=fall_away_choice,
            fall_away_trigger=fall_away_trigger,
            initiation_fee_discount_cents=initiation_fee_discount_cents,
            service_fee_discount_cents=service_fee_discount_cents,
            campaign_id=current.campaign_id,
            version=current.version + 1,
        )
        self.campaigns.replace(edited)
        self._audit(
            actor,
            recognised_at,
            "CAMPAIGN_EDITED",
            before=_campaign_payload(current),
            after=_campaign_payload(edited),
        )
        return edited

    def end_campaign(self, actor: StaffActor, campaign_id: str, recognised_at: datetime) -> Campaign:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        current = self._own_campaign(actor, campaign_id)
        ended = end_campaign(current, value_date(recognised_at))
        self.campaigns.replace(ended)
        self._audit(
            actor,
            recognised_at,
            "CAMPAIGN_ENDED",
            before=_campaign_payload(current),
            after=_campaign_payload(ended),
        )
        return ended

    def list_campaigns(self, actor: StaffActor, organisation_id: str) -> tuple[Campaign, ...]:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.campaigns.list(organisation_id)

    def get_campaign(self, actor: StaffActor, campaign_id: str) -> Campaign:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        return self._own_campaign(actor, campaign_id)

    def preview_fee(
        self,
        actor: StaffActor,
        campaign_id: str,
        *,
        kind: str,
        ex_vat_cents: int,
        vat_rate: Decimal,
    ) -> tuple[int, int, int]:
        require_role(actor, ROLE_CAMPAIGN_WRITE)
        campaign = self._own_campaign(actor, campaign_id)
        if kind == "initiation":
            discount = campaign.initiation_fee_discount_cents
        elif kind == "service":
            discount = campaign.service_fee_discount_cents
        else:
            raise StaffError("fee-kind", "Fee preview kind is initiation or service.")
        return fee_after_discount(ex_vat_cents, vat_rate, discount)

    def put_organisation_elections(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        values: ElectionValues,
    ) -> ElectionValues:
        require_role(actor, ROLE_ELECTIONS_WRITE)
        before = self.elections.get_organisation(actor.organisation_id)
        stored = self.elections.put_organisation(actor.organisation_id, values)
        self._audit(
            actor,
            recognised_at,
            "ELECTION_CHANGED",
            before={"level": "organisation", **_election_payload(before)},
            after={"level": "organisation", **_election_payload(stored)},
        )
        return stored

    def put_product_elections(
        self,
        actor: StaffActor,
        product_id: str,
        recognised_at: datetime,
        values: ElectionValues,
    ) -> ElectionValues:
        require_role(actor, ROLE_ELECTIONS_WRITE)
        before = self.elections.get_product(actor.organisation_id, product_id)
        stored = self.elections.put_product(actor.organisation_id, product_id, values)
        self._audit(
            actor,
            recognised_at,
            "ELECTION_CHANGED",
            before={"level": "product", "product_id": product_id, **_election_payload(before)},
            after={"level": "product", "product_id": product_id, **_election_payload(stored)},
        )
        return stored

    def organisation_elections(self, actor: StaffActor, organisation_id: str) -> ElectionValues:
        require_role(actor, ROLE_ELECTIONS_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.elections.get_organisation(organisation_id)

    def product_elections(self, actor: StaffActor, organisation_id: str, product_id: str) -> ElectionValues:
        require_role(actor, ROLE_ELECTIONS_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.elections.get_product(organisation_id, product_id)

    def require_elections(self, actor: StaffActor, organisation_id: str, product_id: str | None) -> ElectionValues:
        require_role(actor, ROLE_ELECTIONS_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.elections.require(organisation_id, product_id)

    def put_compliance(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        record: ProviderCompliance,
    ) -> ProviderCompliance:
        require_role(actor, ROLE_COMPLIANCE_WRITE)
        if record.organisation_id != actor.organisation_id:
            raise StaffError("mandate-denied", "Compliance is stored on the actor's organisation.", status=403)
        _ncr_present(record.ncr_registration_number)
        before = self.compliance.find(actor.organisation_id)
        self.compliance.put(record)
        stored = self.compliance.require(actor.organisation_id)
        self._audit(
            actor,
            recognised_at,
            "COMPLIANCE_CHANGED",
            before=None if before is None else _compliance_payload(before),
            after=_compliance_payload(stored),
        )
        return stored

    def get_compliance(self, actor: StaffActor, organisation_id: str) -> ProviderCompliance:
        require_role(actor, ROLE_COMPLIANCE_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.compliance.require(organisation_id)

    def put_platform_ceiling(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        *,
        action: str,
        amount_cents: int,
    ) -> RandCeiling:
        require_role(actor, ROLE_CEILING_PLATFORM_WRITE)
        previous = self.ceilings.platform(action)
        version = 1 if previous is None else previous.version + 1
        row = RandCeiling(PLATFORM, action, amount_cents, CURRENCY, "", version)
        self.ceilings.put(row)
        self._audit(
            actor,
            recognised_at,
            "CEILING_CHANGED",
            before=None if previous is None else _ceiling_payload(previous),
            after=_ceiling_payload(row),
        )
        return row

    def put_company_ceiling(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        *,
        action: str,
        amount_cents: int,
    ) -> RandCeiling:
        require_role(actor, ROLE_CEILING_COMPANY_WRITE)
        previous = self.ceilings.company(actor.organisation_id, action)
        version = 1 if previous is None else previous.version + 1
        row = RandCeiling(COMPANY, action, amount_cents, CURRENCY, actor.organisation_id, version)
        self.ceilings.put(row)
        self._audit(
            actor,
            recognised_at,
            "CEILING_CHANGED",
            before=None if previous is None else _ceiling_payload(previous),
            after=_ceiling_payload(row),
        )
        return row

    def list_platform_ceilings(self, actor: StaffActor) -> tuple[RandCeiling, ...]:
        require_role(actor, ROLE_CEILING_PLATFORM_WRITE)
        return self.ceilings.list_platform()

    def list_company_ceilings(self, actor: StaffActor, organisation_id: str) -> tuple[RandCeiling, ...]:
        require_role(actor, ROLE_CEILING_COMPANY_WRITE)
        self._same_organisation(actor, organisation_id)
        return self.ceilings.list_company(organisation_id)

    def apply_ceiling(
        self,
        actor: StaffActor,
        *,
        action: str,
        amount_cents: int,
        organisation_id: str,
    ) -> AppliedCeiling:
        """The tighter limit. This does not write a ceiling and does not post a journal."""
        require_actor(actor)
        integer_cents(amount_cents, "amount")
        return tighter(
            action,
            amount_cents,
            self.ceilings.platform(action),
            self.ceilings.company(organisation_id, action),
        )

    def record_decision(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        *,
        product_id: str | None,
        application_number: str,
        supplied_rate: Decimal,
        credit_life_premium_cents: int,
        maturity_date: date | None,
    ) -> DecisionIntake:
        require_actor(actor)
        recognition = value_date(recognised_at)
        matches = self.campaigns.covering(actor.organisation_id, product_id, recognition)
        row = record_intake(
            organisation_id=actor.organisation_id,
            product_id=product_id,
            application_number=application_number,
            recognition_date=recognition,
            supplied_rate=supplied_rate,
            credit_life_premium_cents=credit_life_premium_cents,
            matches=matches,
            maturity_date=maturity_date,
        )
        self.intakes.add(row)
        self._audit(
            actor,
            recognised_at,
            "DECISION_INTAKE_STORED",
            before=None,
            after={
                "intake_id": row.intake_id,
                "application_number": row.application_number,
                "recognition_date": row.recognition_date.isoformat(),
                "supplied_rate": str(row.supplied_rate),
                "credit_life_premium_cents": row.credit_life_premium_cents,
                "campaign_id": row.campaign_id,
                "campaign_net_rate": None if row.campaign_net_rate is None else str(row.campaign_net_rate),
            },
        )
        return row

    def _own_campaign(self, actor: StaffActor, campaign_id: str) -> Campaign:
        campaign = self.campaigns.get(campaign_id)
        self._same_organisation(actor, campaign.organisation_id)
        return campaign

    def _same_organisation(self, actor: StaffActor, organisation_id: str) -> None:
        if actor.organisation_id != organisation_id:
            raise StaffError(
                "mandate-denied",
                "The Enigma organisation on the command is not the actor's organisation.",
                status=403,
            )

    def _audit(
        self,
        actor: StaffActor,
        recognised_at: datetime,
        event_type: str,
        *,
        before: dict | None,
        after: dict,
    ) -> None:
        self.audit.append(
            organisation_id=actor.organisation_id,
            occurred_at=recognised_at,
            event_type=event_type,
            category="operational",
            enigma_person_id=actor.person_id,
            payload={
                "action": event_type,
                "roles": sorted(actor.roles),
                "recognition_date": value_date(recognised_at).isoformat(),
                "before": before,
                "after": after,
            },
        )


def _ncr_present(ncr_registration_number: str) -> None:
    """Decision 21. Compulsory. A test number of all zeros is a present number."""
    if ncr_registration_number is None or not str(ncr_registration_number).strip():
        raise StaffError(
            "compliance-missing",
            "LOCKED_DECISIONS §21: the NCR registration number is compulsory.",
        )


def _campaign_payload(campaign: Campaign) -> dict:
    return {
        "campaign_id": campaign.campaign_id,
        "organisation_id": campaign.organisation_id,
        "product_id": campaign.product_id,
        "start_date": campaign.start_date.isoformat(),
        "end_date": campaign.end_date.isoformat(),
        "base_rate": str(campaign.base_rate),
        "discount_rate": str(campaign.discount_rate),
        "net_rate": str(campaign.net_rate),
        "fall_away_choice": campaign.fall_away_choice,
        "fall_away_trigger": campaign.fall_away_trigger,
        "initiation_fee_discount_cents": campaign.initiation_fee_discount_cents,
        "service_fee_discount_cents": campaign.service_fee_discount_cents,
        "version": campaign.version,
    }


def _election_payload(values: ElectionValues) -> dict:
    return {
        "vat_on_rand_maxima": values.vat_on_rand_maxima,
        "late_disbursement": values.late_disbursement,
        "partial_prepayment": values.partial_prepayment,
        "interest_on_deferred_initiation": values.interest_on_deferred_initiation,
        "repo_rate_fall": values.repo_rate_fall,
        "in_duplum_trigger": values.in_duplum_trigger,
        "residual_write_off_threshold_cents": values.residual_write_off_threshold_cents,
        "campaign_fall_away_choice": values.campaign_fall_away_choice,
        "campaign_fall_away_trigger": values.campaign_fall_away_trigger,
    }


def _compliance_payload(record: ProviderCompliance) -> dict:
    return {
        "organisation_id": record.organisation_id,
        "legal_name": record.legal_name,
        "ncr_registration_number": record.ncr_registration_number,
        "trading_name": record.trading_name,
        "physical_address": record.physical_address,
        "postal_address": record.postal_address,
        "telephone": record.telephone,
        "bank_name": record.bank_name,
        "bank_account_number": record.bank_account_number,
        "branch_code": record.branch_code,
        "payment_reference": record.payment_reference,
    }


def _ceiling_payload(row: RandCeiling) -> dict:
    return {
        "scope": row.scope,
        "action": row.action,
        "amount_cents": row.amount_cents,
        "currency": row.currency,
        "organisation_id": row.organisation_id,
        "version": row.version,
    }
