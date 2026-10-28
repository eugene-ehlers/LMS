# Enigma port implementation note

28 October 2026 (Africa/Johannesburg). Source of truth: `docs/LOCKED_DECISIONS.md`. Design: `docs/enigma/lms-enigma-interface.md`.

HTTP paths are not invented. `UnboundHttpEnigmaPort` and `UnboundMachineIdentity` raise `UnboundEnigmaPort`. Conflicts C1–C10 in the design are still open. This note does not close them.

## Client signatures and errors

`EnigmaClient` in `src/lms/enigma/client.py`:

| Method | Port operation | Locked section |
| --- | --- | --- |
| `introspect(session_ref, *, request_id) -> SessionView` | `session.introspect` | 15, ambiguous status fails closed |
| `organisation_context(session_ref, organisation_id, *, request_id) -> OrganisationContext` | `organisation.context` | 15 |
| `validate_membership(session_ref, person_id, organisation_id, *, request_id) -> Membership` | `membership.validate` | 15 |
| `lookup_mandate(query: MandateQuery, *, request_id) -> MandateDecision` | `mandate.lookup` | 15 |
| `check_enrolment(session_ref, organisation_id, product_code, *, request_id) -> Enrolment` | `enrolment.check` | 15. A clear `suspended` is port decision 3 (conflict C3) |

`MandateQuery` fields: `session_ref`, `person_id`, `organisation_id`, `action`, `product_code`.

| Error | HTTP | When |
| --- | --- | --- |
| `Reauthenticate` | 401 | Missing, expired, revoked, or audience other than `lms` |
| `NotAMember` | 403 | Membership `absent` or `suspended` |
| `OrganisationUnavailable` | 403 | Organisation `suspended`, `closed`, or a different id |
| `EnrolmentDenied` | 403 | Enrolment `suspended` or `absent`, including on a read |
| `MandateDenied` | 403 | Lookup `deny`, or an allocation member asks for anything but `lms.allocation.run` |
| `OrganisationContextStale` | 409 | Cookie generation is behind |
| `AttributesUnavailable` | 409 | Booking is missing name, ID number, or service address |
| `AuthorityUnavailable` | 503 | Timeout or HTTP 5xx. Locked section 15 |
| `AmbiguousAuthority` | 503 | Status is not a known clear answer. Locked section 15 |
| `UnboundEnigmaPort` | 503 | The call has no HTTP path |

## Middleware

`establish_session` and `handle_request` in `src/lms/enigma/middleware.py`.

Every request calls `introspect`. Timeout and HTTP 5xx become `authority_unavailable`. An unclear sign-in, membership, role, organisation, or enrolment becomes `authority_ambiguous`, except a clear `suspended` or `absent` enrolment, which is `enrolment_denied`. A cookie generation that does not match the server session is `409` `organisation_context_stale`, and the loan is not read. A switch to a different organisation increments the generation only after organisation context and membership succeed for the target.

Locked section 15 covers the introspect and the fail-closed. The generation counter is not in the locked file.

## Identity freeze

`freeze_at_booking` copies `name`, `id_number`, and `service_address` onto a new `AgreementIdentity` (locked section 16). Nothing in the module writes an existing agreement. A later read of the live person does not change the object already returned. Email and mobile are a separate live read and are not frozen (conflict C10).

## Machine identity

`MachineIdentityPort.exchange(proof, *, request_id) -> str` is the interface. Enigma is the side that verifies the IAM task role. `UnboundMachineIdentity.exchange` raises `UnboundEnigmaPort`.

`handle_machine_request` then runs the five checks for `proof.organisation_id`. `ALLOCATION_ALLOWED_ACTIONS` is `{lms.allocation.run}`. `lms.account.write_off` returns `mandate_denied` even if `lookup_mandate` would allow it. That limit is port decision 2, not a sentence in locked section 15 (conflict C9). It is not a stored staff list.

## Still needed from Enigma

1. HTTP paths and how LMS authenticates as a consumer.
2. Cognito callback shape and the audience claim.
3. Real role ids. The strings `lms.staff.admin`, `lms.ceiling.platform.write`, and `lms.ceiling.company.write` are port names.
4. The IAM exchange request and the machine session it returns.
5. Field names for name, ID number, service address, and, separately, email and mobile.
6. Whether introspect returns `bound_organisation_id`.
7. Catalogue strings for the four product codes. `lms.laybye_security` conflicts with locked section 4 (C4).
8. Event signature and delivery.
9. Where day-count, repo-rate choice, leniency, and tariffs are stored (conflicts C6). This port does not create those tables.

## Tests

`python3 -m pytest tests/test_enigma_session.py` — 15 passed on 28 October 2026 (Africa/Johannesburg).

Pinned: timeout and HTTP 5xx are `authority_unavailable`; an unknown session status is `authority_ambiguous`; a suspended enrolment on a read is `enrolment_denied`; organisation switch moves generation from 1 to 2 and the old generation is `409`; booking freezes name, ID number, and service address and ignores a later Enigma edit; an allocation session can run `lms.allocation.run` and cannot write off; each unbound operation raises `UnboundEnigmaPort`.
