from datetime import datetime, timezone

import pytest

from lms.enigma.ceilings import authorize_ceiling_change, enforce_amount
from lms.enigma.client import EnigmaClient
from lms.enigma.errors import (
    AttributesUnavailable,
    MandateDenied,
    TransportHTTPError,
    TransportTimeout,
    UnboundEnigmaPort,
)
from lms.enigma.identity_freeze import communication_preferences, freeze_at_booking
from lms.enigma.machine import UnboundMachineIdentity, handle_machine_request
from lms.enigma.middleware import IncomingRequest, MemorySessionStore, establish_session, handle_request
from lms.enigma.port import UnboundHttpEnigmaPort
from lms.enigma.models import (
    COMPANY_CEILING_ROLE,
    PLATFORM_CEILING_ROLE,
    PRODUCT_BNPL_LAYBYE,
    PRODUCT_MICRO,
    Enrolment,
    LiveIdentity,
    MandateDecision,
    Membership,
    OrganisationContext,
    OrganisationMembershipSummary,
    RandCeiling,
    IamCallerProof,
    SessionView,
)
from lms.enigma.regulatory import ncr_number_required

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)


class FakePort:
    def __init__(self) -> None:
        self.fail: Exception | None = None
        self.session_status = "active"
        self.audience = "lms"
        self.sign_in_clear = True
        self.person_id = "per_12"
        self.bound_organisation_id = None
        self.roles = ("lms.account.read",)
        self.membership_status = "active"
        self.org_status = "active"
        self.enrolment_status = "active"
        self.decision = "allow"
        self.mandate_id = "man_88"
        self.mandate_version = 4

    def introspect(self, session_ref: str, *, request_id: str) -> SessionView:
        self._raise()
        return SessionView(
            status=self.session_status,  # type: ignore[arg-type]
            person_id=self.person_id,
            audience=self.audience,
            expires_at=NOW,
            bound_organisation_id=self.bound_organisation_id,
            organisations=(
                OrganisationMembershipSummary("org_a", "active"),
                OrganisationMembershipSummary("org_b", "active"),
            ),
            sign_in_clear=self.sign_in_clear,
            enigma_request_id="req_intro",
        )

    def organisation_context(self, session_ref, organisation_id, *, request_id: str):
        self._raise()
        return OrganisationContext(
            organisation_id=organisation_id,
            status=self.org_status,
            legal_name="Cape Credit",
            trading_name="Cape Credit",
            enigma_request_id="req_org",
        )

    def validate_membership(self, session_ref, person_id, organisation_id, *, request_id: str):
        self._raise()
        return Membership(
            status=self.membership_status,
            membership_id="mem_1",
            membership_version=3,
            roles=self.roles,
            enigma_request_id="req_mem",
        )

    def lookup_mandate(self, query, *, request_id: str):
        self._raise()
        return MandateDecision(
            decision=self.decision,
            reason="ok" if self.decision == "allow" else "scope_mismatch",
            mandate_id=self.mandate_id,
            mandate_version=self.mandate_version,
            enigma_request_id="req_man",
        )

    def check_enrolment(self, session_ref, organisation_id, product_code, *, request_id: str):
        self._raise()
        return Enrolment(
            status=self.enrolment_status,
            enrolment_id="enr_1" if self.enrolment_status == "active" else None,
            enrolment_version=2,
            product_code=product_code,
            enigma_request_id="req_enr",
        )

    def _raise(self) -> None:
        if self.fail:
            raise self.fail


class FakeCeilings:
    def __init__(self) -> None:
        self.platform_ceiling = RandCeiling("platform", "lms.account.write_off", 1_000_00, "ZAR", None, 1)
        self.company_ceiling = RandCeiling("company", "lms.account.write_off", 1_000_00, "ZAR", "org_a", 7)

    def platform(self, action: str):
        if self.platform_ceiling and self.platform_ceiling.action == action:
            return self.platform_ceiling
        return None

    def company(self, organisation_id: str, action: str):
        row = self.company_ceiling
        if row and row.action == action and row.organisation_id == organisation_id:
            return row
        return None


def _ready():
    port = FakePort()
    store = MemorySessionStore()
    client = EnigmaClient(port)
    opened = establish_session(
        "sess_9c2",
        "org_a",
        sessions=store,
        client=client,
        request_id="req_open",
        lms_session_id="lms_1",
    )
    assert opened.status == 200
    return port, store, client, FakeCeilings()


def test_active_request_trusts_enigma_membership_and_role():
    port, store, client, ceilings = _ready()
    result = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_1",
    )
    assert result.status == 200
    assert result.person_id == "per_12"
    assert result.mandate_id == "man_88"
    assert result.enrolment_id == "enr_1"


def test_stale_generation_is_409_and_does_not_need_a_new_organisation():
    port, store, client, ceilings = _ready()
    switched = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", switch_to_organisation_id="org_b"),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_switch",
    )
    assert switched.status == 200
    assert switched.organisation_generation == 2
    assert switched.organisation_id == "org_b"

    stale = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_stale",
    )
    assert stale.status == 409
    assert stale.error == "organisation_context_stale"
    assert stale.organisation_generation == 2
    assert store.get("lms_1").active_organisation_id == "org_b"


def test_timeout_and_5xx_fail_closed():
    port, store, client, ceilings = _ready()
    port.fail = TransportTimeout()
    timed_out = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_timeout",
    )
    assert timed_out.status == 503
    assert timed_out.error == "authority_unavailable"

    port.fail = TransportHTTPError(502)
    bad_gateway = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_502",
    )
    assert bad_gateway.status == 503
    assert bad_gateway.error == "authority_unavailable"


def test_unclear_sign_in_membership_and_enrolment_stop():
    port, store, client, ceilings = _ready()
    port.sign_in_clear = False
    unclear = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_unclear",
    )
    assert unclear.status == 503
    assert unclear.error == "authority_ambiguous"

    port.sign_in_clear = True
    port.roles = ()
    no_role = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_role",
    )
    assert no_role.error == "authority_ambiguous"

    port.roles = ("collections",)
    port.enrolment_status = "suspended"
    suspended = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_enrol",
    )
    assert suspended.status == 403
    assert suspended.error == "enrolment_denied"


def test_wrong_audience_reauthenticates():
    port = FakePort()
    port.audience = "product-idip"
    result = establish_session(
        "sess_idip",
        "org_a",
        sessions=MemorySessionStore(),
        client=EnigmaClient(port),
        request_id="req_aud",
    )
    assert result.status == 401
    assert result.error == "reauthenticate"


def test_write_off_uses_the_tighter_ceiling():
    platform = RandCeiling("platform", "lms.account.write_off", 1_000_000, "ZAR", None, 1)
    company = RandCeiling("company", "lms.account.write_off", 100_000, "ZAR", "org_a", 4)
    applied = enforce_amount(
        action="lms.account.write_off",
        amount_cents=100_000,
        platform=platform,
        company=company,
    )
    assert applied.limit_cents == 100_000
    with pytest.raises(MandateDenied):
        enforce_amount(
            action="lms.account.write_off",
            amount_cents=150_000,
            platform=platform,
            company=company,
        )


def test_missing_platform_ceiling_is_ambiguous():
    port, store, client, ceilings = _ready()
    ceilings.platform_ceiling = None
    result = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.write_off", PRODUCT_MICRO, amount_cents=50_000),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_ceiling",
    )
    assert result.status == 503
    assert result.error == "authority_ambiguous"


def test_ceiling_editors_are_role_gated():
    company_admin = Membership("active", "mem", 1, (COMPANY_CEILING_ROLE,), "req")
    authorize_ceiling_change(
        company_admin,
        scope="company",
        actor_organisation_id="org_a",
        target_organisation_id="org_a",
        platform_organisation_id="org_tsdg",
    )
    with pytest.raises(MandateDenied):
        authorize_ceiling_change(
            company_admin,
            scope="platform",
            actor_organisation_id="org_a",
            target_organisation_id="org_tsdg",
            platform_organisation_id="org_tsdg",
        )
    platform_admin = Membership("active", "mem", 1, (PLATFORM_CEILING_ROLE,), "req")
    authorize_ceiling_change(
        platform_admin,
        scope="platform",
        actor_organisation_id="org_tsdg",
        target_organisation_id="org_tsdg",
        platform_organisation_id="org_tsdg",
    )


def test_booking_freezes_three_fields_and_leaves_later_changes_alone():
    class Directory:
        def __init__(self) -> None:
            self.live = LiveIdentity(
                "per_12",
                "Thandi Nkosi",
                "8001015009087",
                "12 Loop Street, Cape Town",
                "thandi@example.com",
                "0820000000",
                "email",
                "req_id",
            )

        def read_live_identity(self, person_id: str, *, request_id: str) -> LiveIdentity:
            return self.live

    directory = Directory()
    frozen = freeze_at_booking(directory, "per_12", frozen_at=NOW, request_id="book")
    directory.live = LiveIdentity(
        "per_12",
        "Thandi Nkosi-Dlamini",
        "8001015009087",
        "99 New Street, Johannesburg",
        "new@example.com",
        None,
        "email",
        "req_later",
    )
    assert frozen.name == "Thandi Nkosi"
    assert frozen.service_address == "12 Loop Street, Cape Town"
    assert frozen.id_number == "8001015009087"
    prefs = communication_preferences(directory, "per_12", request_id="send")
    assert prefs.email == "new@example.com"
    assert not hasattr(frozen, "email")


def test_booking_refuses_a_blank_identity_field():
    class Directory:
        def read_live_identity(self, person_id: str, *, request_id: str) -> LiveIdentity:
            return LiveIdentity("per_12", "Thandi Nkosi", "  ", "12 Loop Street", None, None, None, "req")

    with pytest.raises(AttributesUnavailable):
        freeze_at_booking(Directory(), "per_12", frozen_at=NOW, request_id="book")


def test_ncr_number_is_required_only_for_nca_products():
    assert ncr_number_required(product_code=PRODUCT_MICRO, pure_hosting=False)
    assert not ncr_number_required(product_code=PRODUCT_BNPL_LAYBYE, pure_hosting=False)
    assert not ncr_number_required(product_code=PRODUCT_MICRO, pure_hosting=True)


def test_suspended_enrolment_fails_closed_on_a_read():
    port, store, client, ceilings = _ready()
    port.enrolment_status = "suspended"
    result = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_suspended",
    )
    assert result.status == 403
    assert result.error == "enrolment_denied"


def test_ambiguous_session_status_fails_closed():
    port, store, client, ceilings = _ready()
    port.session_status = "pending"
    result = handle_request(
        IncomingRequest("lms_1", 1, "lms.account.read", PRODUCT_MICRO),
        sessions=store,
        client=client,
        ceilings=ceilings,
        request_id="req_pending",
    )
    assert result.status == 503
    assert result.error == "authority_ambiguous"


class _AllowingMachines:
    def exchange(self, proof: IamCallerProof, *, request_id: str) -> str:
        return "sess_machine"


def test_machine_allocation_runs_and_write_off_is_denied():
    port = FakePort()
    port.decision = "allow"
    client = EnigmaClient(port)
    proof = IamCallerProof(presigned_url="presigned-get-caller-identity", organisation_id="org_a")
    allocated = handle_machine_request(
        proof,
        action="lms.allocation.run",
        product_code=PRODUCT_MICRO,
        machines=_AllowingMachines(),
        client=client,
        request_id="req_alloc",
    )
    assert allocated.status == 200
    assert allocated.mandate_id == "man_88"

    port.decision = "allow"
    denied = handle_machine_request(
        proof,
        action="lms.account.write_off",
        product_code=PRODUCT_MICRO,
        machines=_AllowingMachines(),
        client=client,
        request_id="req_write_off",
    )
    assert denied.status == 403
    assert denied.error == "mandate_denied"


def test_unbound_path_raises_unbound_enigma_port():
    port = UnboundHttpEnigmaPort()
    client = EnigmaClient(port)
    with pytest.raises(UnboundEnigmaPort):
        port.introspect("sess", request_id="req")
    with pytest.raises(UnboundEnigmaPort):
        port.organisation_context("sess", "org_a", request_id="req")
    with pytest.raises(UnboundEnigmaPort):
        port.validate_membership("sess", "per_12", "org_a", request_id="req")
    with pytest.raises(UnboundEnigmaPort):
        port.lookup_mandate(None, request_id="req")  # type: ignore[arg-type]
    with pytest.raises(UnboundEnigmaPort):
        client.check_enrolment("sess", "org_a", PRODUCT_MICRO, request_id="req")
    with pytest.raises(UnboundEnigmaPort):
        UnboundMachineIdentity().exchange(
            IamCallerProof("presigned", "org_a"),
            request_id="req",
        )
    with pytest.raises(UnboundEnigmaPort):
        freeze_at_booking(port, "per_12", frozen_at=NOW, request_id="req")
