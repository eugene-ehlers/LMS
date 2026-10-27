"""Machine identity for allocation and other non-human jobs.

Target pattern, parallel to human sign-on:

- Humans: Cognito authenticates the person. Enigma maps that identity to membership and roles.
- Machines: the workload's AWS IAM role authenticates the process. Enigma maps the role ARN to a
  machine member whose allowed actions are an explicit list.

LMS does not keep the machine list and does not copy a staff session into a batch.
``UnboundMachineIdentity`` is the stand-in until Enigma exposes the IAM exchange.
"""

from __future__ import annotations

from lms.enigma.errors import WireUnbound
from lms.enigma.models import IamCallerProof


class UnboundMachineIdentity:
    def exchange(self, proof: IamCallerProof, *, request_id: str) -> str:
        raise WireUnbound("IAM caller exchange is unbound")
