"""Freeze name, ID number, and service address onto an agreement at booking.

The returned value is the concluded agreement's identity. Communication preferences stay
on the live Enigma person and are read again when a message is sent. A later change to the
live record is not copied back onto the agreement.
"""

from __future__ import annotations

from datetime import datetime

from lms.enigma.errors import (
    AmbiguousAuthority,
    AttributesUnavailable,
    AuthorityUnavailable,
    TransportHTTPError,
    TransportTimeout,
)
from lms.enigma.models import AgreementIdentity, CommunicationPreferences, LiveIdentity
from lms.enigma.port import PersonDirectory


def freeze_at_booking(
    directory: PersonDirectory,
    person_id: str,
    *,
    frozen_at: datetime,
    request_id: str,
) -> AgreementIdentity:
    live = _read(directory, person_id, request_id=request_id)
    if live.person_id != person_id:
        raise AmbiguousAuthority(
            "identity answer is for a different person",
            enigma_request_id=live.enigma_request_id,
        )
    name = live.name.strip()
    id_number = live.id_number.strip()
    service_address = live.service_address.strip()
    if not name or not id_number or not service_address:
        raise AttributesUnavailable(
            "name, id number, and service address are required at booking",
            enigma_request_id=live.enigma_request_id,
        )
    return AgreementIdentity(
        person_id=person_id,
        name=name,
        id_number=id_number,
        service_address=service_address,
        frozen_at=frozen_at,
        source_request_id=live.enigma_request_id,
    )


def communication_preferences(
    directory: PersonDirectory,
    person_id: str,
    *,
    request_id: str,
) -> CommunicationPreferences:
    """Live preferences. Callers must not persist these onto the concluded agreement."""

    live = _read(directory, person_id, request_id=request_id)
    if live.person_id != person_id:
        raise AmbiguousAuthority(
            "identity answer is for a different person",
            enigma_request_id=live.enigma_request_id,
        )
    if not (live.email or live.mobile):
        raise AttributesUnavailable(
            "no live communication channel",
            enigma_request_id=live.enigma_request_id,
        )
    return CommunicationPreferences(
        person_id=person_id,
        email=live.email,
        mobile=live.mobile,
        preferred_channel=live.preferred_channel,
        enigma_request_id=live.enigma_request_id,
    )


def _read(directory: PersonDirectory, person_id: str, *, request_id: str) -> LiveIdentity:
    try:
        return directory.read_live_identity(person_id, request_id=request_id)
    except TransportTimeout as exc:
        raise AuthorityUnavailable("enigma timeout") from exc
    except TransportHTTPError as exc:
        if exc.status >= 500:
            raise AuthorityUnavailable(f"enigma http {exc.status}") from exc
        raise AmbiguousAuthority(f"enigma http {exc.status}") from exc
