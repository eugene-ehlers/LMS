# Layer 1 implementation checklist — Enigma port

**Draft.** Not production code. Not a change to `docs/LOCKED_DECISIONS.md`.

Date: 27 October 2026 (Africa/Johannesburg). Source of truth: `docs/LOCKED_DECISIONS.md` as merged from main commit `d19f4ea` (22:10, Africa/Johannesburg). Port design: `docs/enigma/lms-enigma-interface.md`.

`src/lms/enigma/` is an earlier draft sketch. This checklist does not extend it. Signatures below are the sketch's names, marked where a locked rule already requires the behaviour and where the sketch goes past the locked file.

Do not hard-code example values from locked section 6 (4 days, 5 days, 95 percent) as defaults. Do not turn on the in-duplum clip. Do not choose option A or option B when a provider choice is unset.

## Data structures

| Structure | Fields this checklist will use | Status |
| --- | --- | --- |
| Opaque keys | `person_id`, `organisation_id` | Required by locked section 15. No other identity columns are authorised by that section |
| Agreement freeze | `person_id`, `name`, `id_number`, `service_address` | Required by locked section 16. Later Enigma changes do not write these fields |
| Freeze technical columns | `frozen_at`, `source_request_id` | Not named in the locked file. Sketch-only. Do not treat them as part of section 16 |
| Communication preferences | `email`, `mobile`, `preferred_channel` | Not in section 16. Port decision 6 reads them live and does not put them on the freeze. Conflict C10 |
| Session row | `lms_session_id`, `session_ref`, `person_id`, `active_organisation_id`, `organisation_generation` | Sketch. `person_id` and `organisation_id` match section 15. The session reference and generation are not in the locked file. Conflict C2 |
| Authority snapshot | `person_id`, `organisation_id`, `mandate_id`, `mandate_version`, `enrolment_id`, `enrolment_version`, `action`, `decided_at` | Sketch audit of an Enigma answer. Mandate and enrolment ids are not authorised as stores by section 15. Conflict C2 |
| Ceiling versions on the snapshot | `platform_ceiling_version`, `company_ceiling_version` | Port decision 5. Absent from the locked file. Conflict C2 |
| NCR attribute | number on the tenant, keyed by `organisation_id` | Port decision 4. Absent from the locked file. Conflict C2 |
| Provider-choice rows | day count, deferred-initiation interest, repo-rate option | Locked sections 5, 10, and 11 require the choice to exist per organisation or per product, and section 11 fails closed when unset. The locked file does not name the table. Do not create it in this layer. Conflict C6 |
| Customer default settings | `leniency_days`, `full_payment_threshold_percent` | Locked section 6. Per customer. Unset fails closed. Storage owner is not stated. Conflict C6 |
| Tariff row | default-administration and collection-cost tariff | Locked section 18. Missing row fails closed. Not an Enigma object in the locked file |
| Machine registration | role ARN, `organisation_id`, allowed actions | Port decision 2. Not in the locked file. Conflict C9. Held by Enigma in the sketch, not by LMS |
| Laybye link | parent loan and child Laybye | Locked section 4 requires the relationship and says the pair is one loan. The column shape is not specified. Do not invent it here |
| Statement | one statement per client, all loans | Locked section 12. The sketch action is per account. Conflict C5 |

## Function signatures

Draft names from `src/lms/enigma/`. A signature stays only if the note says the locked file already requires the behaviour, or the note says it is sketch-only and blocked by a conflict.

| Signature | Note |
| --- | --- |
| `EnigmaClient.introspect(session_ref, *, request_id) -> SessionView` | Sketch of session validation. Locked section 15 requires fail closed on timeout or ambiguous status. It does not name this method |
| `EnigmaClient.organisation_context(session_ref, organisation_id, *, request_id) -> OrganisationContext` | Sketch. Organisation identity stays in Enigma (section 15) |
| `EnigmaClient.validate_membership(session_ref, person_id, organisation_id, *, request_id) -> Membership` | Sketch. Membership stays in Enigma (section 15). Empty `roles` is a stop in port decision 3, which is wider than section 15 |
| `EnigmaClient.lookup_mandate(query, *, request_id) -> MandateDecision` | Sketch. Roles and mandates stay in Enigma (section 15). An amount ceiling applied after `allow` is port decision 5, not a locked sentence |
| `EnigmaClient.check_enrolment(session_ref, organisation_id, product_code, *, request_id) -> Enrolment` | Sketch. Product enrolment stays in Enigma (section 15). Stopping a clear `suspended` enrolment is port decision 3. Conflict C3 |
| `freeze_at_booking(...) -> AgreementIdentity` | Required behaviour from locked section 16: copy name, ID number, and service address, and do not rewrite them from a later Enigma read. Blank-field refusal is port decision 6, not a sentence in section 16 |
| `communication_preferences(...)` | Port decision 6. Not in section 16. Conflict C10 |
| `enforce_amount(...)` and `authorize_ceiling_change(...)` | Port decision 5. Not in the locked file. Conflict C2. Do not describe these as section 103(5) |
| `ncr_number_required(...)` | Port decision 4. Not in the locked file. Conflict C2 |
| `establish_session` / `handle_request` | Sketch. Generation `409` is a port mechanic. Locked section 15's fail closed covers timeout and ambiguous status |
| `MachineIdentityPort.exchange` | Port decision 2. Not in the locked file. Conflict C9. `UnboundMachineIdentity` stays unbound |

`query` on `lookup_mandate` carries `session_ref`, `person_id`, `organisation_id`, `action`, and `product_code`. Those names are sketch fields.

## Invariants

Hold these. Do not add a default when one is missing.

1. Enigma is the only registry for person identity, organisations, memberships, product enrolment, roles, and mandates.
2. LMS persistence of identity is opaque `person_id` and `organisation_id`, plus the three frozen agreement fields in locked section 16.
3. A later Enigma change does not rewrite a concluded agreement's name, ID number, or service address.
4. An Enigma timeout fails closed. An ambiguous Enigma status fails closed. The command is not committed.
5. Unset `leniency_days` or `full_payment_threshold_percent` fails closed. Example numbers are not defaults.
6. The in-duplum clip stays off while the three section 103(5) edges are unsigned.
7. A missing provider choice for the rate after a repo-rate fall fails closed. There is no platform default.
8. A missing default-administration or collection-cost tariff row fails closed.
9. Section 126 order is interest, then fees or charges, then principal. The port does not return that order.
10. One statement is per client and shows all loans.
11. A "subsequent" short-term loan is counted per credit-provider organisation.
12. The value date of allocation and reversals is the system recognition date, treated as 00:00 on that calendar day. This checklist does not move the Enigma session clock to 00:00.
13. Rounding, where rounding is required for billing, is half-up to cents, and the same rule everywhere. It must not put an instalment above the affordability figure already aligned with the client. This checklist does not apply that round to the sketch's operational ceiling.
14. The sketch must not be extended while conflicts C1–C10 are open.

## Technical open questions

These are gaps. They are not proposals.

1. Locked section 15's "only" and locked section 16's three frozen fields are both in force. The locked file does not say how an implementer stores the freeze without breaking the "only".
2. The locked file does not say whether legal name, the NCR number, operational ceilings, mandate ids, or the session reference may be stored beside the opaque ids.
3. The locked file does not say that a clear `suspended` enrolment fails closed. Port decision 3 does.
4. The locked file does not give the product-code string for the linked Laybye, and section 4 rejects describing that Laybye as security that would make the loan secured. The sketch string `lms.laybye_security` is unresolved against that sentence.
5. The locked file does not name the statement action. The sketch name is per account. Section 12 is per client.
6. The locked file does not say which system stores day-count, deferred-initiation interest, the repo-rate choice, leniency days, or the full-payment threshold.
7. The locked file does not say whether the Enigma mandate or session is evaluated at 00:00 on the value date or at the time of the call.
8. The locked file does not say that a beneficiary or a section 124 authority is an Enigma object.
9. The locked file does not describe machine authentication or the staff-list admin role.
10. The locked file does not mention communication preferences. Port decision 6 reads them live.
11. Enigma's HTTP paths, consumer authentication, Cognito callback shape, real role ids, IAM exchange, person field names, organisation-bound sessions, catalogue codes, and event signatures are still unread, because `eugene-ehlers/enigma` was not readable from this environment. `consumer_contract.py` has not been checked against this checklist.
