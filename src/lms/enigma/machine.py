"""Machine identity for the allocation job.

Enigma verifies the IAM task role and returns a machine session. That exchange has no HTTP
path yet, so ``UnboundMachineIdentity`` raises ``UnboundEnigmaPort``.

The allocation member's allowed actions are only ``lms.allocation.run``. Any other action,
including write-off, is ``mandate_denied`` before a posting. Locked decision 15 puts mandates
in Enigma and does not describe this job (conflict C9). The action set is the port contract
for this one member, not a staff table and not configuration storage.
"""

from __future__ import annotations

from lms.enigma.client import EnigmaClient
from lms.enigma.errors import MandateDenied, PortError, UnboundEnigmaPort
from lms.enigma.middleware import HttpResult
from lms.enigma.models import IamCallerProof, MandateQuery
from lms.enigma.port import MachineIdentityPort

ALLOCATION_ACTION = "lms.allocation.run"
ALLOCATION_ALLOWED_ACTIONS = frozenset({ALLOCATION_ACTION})


class UnboundMachineIdentity:
    def exchange(self, proof: IamCallerProof, *, request_id: str) -> str:
        raise UnboundEnigmaPort("IAM caller exchange has no HTTP path")


def handle_machine_request(
    proof: IamCallerProof,
    *,
    action: str,
    product_code: str,
    machines: MachineIdentityPort,
    client: EnigmaClient,
    request_id: str,
) -> HttpResult:
    """Run one non-human action after Enigma has exchanged the IAM proof for a session."""

    try:
        session_ref = machines.exchange(proof, request_id=request_id)
        view = client.introspect(session_ref, request_id=request_id)
        client.organisation_context(
            session_ref, proof.organisation_id, request_id=request_id
        )
        client.validate_membership(
            session_ref, view.person_id, proof.organisation_id, request_id=request_id
        )
        enrolment = client.check_enrolment(
            session_ref, proof.organisation_id, product_code, request_id=request_id
        )
        if action not in ALLOCATION_ALLOWED_ACTIONS:
            raise MandateDenied("allocation member is limited to lms.allocation.run")
        decision = client.lookup_mandate(
            MandateQuery(
                session_ref=session_ref,
                person_id=view.person_id,
                organisation_id=proof.organisation_id,
                action=action,
                product_code=product_code,
            ),
            request_id=request_id,
        )
        return HttpResult(
            status=200,
            error=None,
            person_id=view.person_id,
            organisation_id=proof.organisation_id,
            mandate_id=decision.mandate_id,
            mandate_version=decision.mandate_version,
            enrolment_id=enrolment.enrolment_id,
            enrolment_version=enrolment.enrolment_version,
            enigma_request_id=decision.enigma_request_id,
        )
    except PortError as exc:
        return HttpResult(
            status=exc.http_status,
            error=exc.code,
            enigma_request_id=exc.enigma_request_id,
        )
