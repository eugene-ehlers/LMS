# Enigma dummy

Enigma is identity and access. The LMS stores opaque `person_id` and `organisation_id`. It does not re-implement person or organisation identity.

The dummy is one fixed directory. There is no scenario switch and no network call. Tests select a result by the token, person id, or organisation id below. An unknown or unusable status fails closed: the call raises `EnigmaFailClosed` and returns no object the LMS can treat as access or as a complete identity.

Which reading of “address” is correct is not locked. Decision 16 freezes a consumer service address and says later Enigma changes must not rewrite the agreement. Decisions 15 and 21 say Enigma does not return addresses, in the credit-provider compliance list. This dummy returns the consumer service address only from `identity_for_booking`. `organisation.context` does not return an address, trading name, NCR number, telephone, payment-account details, brand, ceiling, or campaign.

Email and telephone are not on any LMS response. Enigma may hold them for registered users; the LMS does not store them.

## Call sites

| Operation | Call |
| --- | --- |
| `session.introspect` | `enigma.session.introspect(session_token)` |
| `organisation.context` | `enigma.organisation.context(organisation_id)` |
| `membership` | `enigma.membership(person_id, organisation_id)` |
| `enrolment` | `enigma.enrolment(person_id, organisation_id)` |
| `lookup_mandate` | `enigma.lookup_mandate(person_id, organisation_id, role)` |
| Booking identity | `enigma.identity_for_booking(person_id)` |

The booking freeze the LMS stores is `freeze_booking_identity(identity)`. That copies name, ID number and service address into a new value and does not copy `person_id`. The LMS keeps `person_id` separately. Replacing the dummy does not change these call sites.

A suspended enrolment fails `membership`, `enrolment` and `lookup_mandate`. It does not erase the person record, so `session.introspect` and `identity_for_booking` still succeed when the person record itself is clear. Timeout and an ambiguous person record fail those reads as well.

A missing role on an active enrolment returns `granted: false`. That is a clear denial, not an ambiguous status. No enrolment returns `not_enrolled`. An unknown token, person, or organisation fails closed with `unknown_session`, `unknown_person`, or `unknown_organisation`.

## Fixed directory

### Sessions

| Token | Person | `session.introspect` |
| --- | --- | --- |
| `session-active` | `person-active` | `person_id = person-active` |
| `session-no-mandate` | `person-no-mandate` | `person_id = person-no-mandate` |
| `session-suspended` | `person-suspended` | `person_id = person-suspended` |
| `session-unenrolled` | `person-unenrolled` | `person_id = person-unenrolled` |
| `session-enrolment-ambiguous` | `person-enrolment-ambiguous` | `person_id = person-enrolment-ambiguous` |
| `session-ambiguous` | `person-ambiguous` | Fail closed `ambiguous_status` |
| `session-timeout` | `person-timeout` | Fail closed `timeout` |
| any other token | | Fail closed `unknown_session` |

A blank token is a contract error.

### People

| `person_id` | Name | ID number | Service address | Record |
| --- | --- | --- | --- | --- |
| `person-active` | Test Consumer | `0000000000000` | 1 Dummy Street, Johannesburg | Clear |
| `person-no-mandate` | Test Staff Without Mandate | `0000000000001` | 2 Dummy Street, Johannesburg | Clear |
| `person-suspended` | Suspended Consumer | `0000000000002` | 3 Dummy Street, Johannesburg | Clear |
| `person-ambiguous` | Ambiguous Consumer | `0000000000003` | 4 Dummy Street, Johannesburg | Ambiguous |
| `person-timeout` | Timeout Consumer | `0000000000004` | 5 Dummy Street, Johannesburg | Timeout |
| `person-unenrolled` | Unenrolled Consumer | `0000000000005` | 6 Dummy Street, Johannesburg | Clear |
| `person-enrolment-ambiguous` | Ambiguous Enrolment | `0000000000006` | 7 Dummy Street, Johannesburg | Clear |

`identity_for_booking` on a clear record returns `person_id`, `name`, `id_number` and `service_address`. An ambiguous record fails closed `ambiguous_status`. A timeout record fails closed `timeout`. An unknown person fails closed `unknown_person`. None of those failures return the name, ID number, or address.

### Organisations

`organisation.context` returns only:

| Field | Type |
| --- | --- |
| `organisation_id` | string |
| `company_registration_number` | string |

| `organisation_id` | Company registration | Result |
| --- | --- | --- |
| `org-active` | `2020/000000/07` | Returned |
| `org-other` | `2021/000000/07` | Returned |
| `org-ambiguous` | not returned | Fail closed `ambiguous_status` |
| `org-timeout` | not returned | Fail closed `timeout` |
| any other id | | Fail closed `unknown_organisation` |

### Enrolments

| Person | Organisation | Enrolment | Roles |
| --- | --- | --- | --- |
| `person-active` | `org-active` | Active | `lms.agreements.read`, `lms.elections.write` |
| `person-no-mandate` | `org-active` | Active | none |
| `person-suspended` | `org-active` | Suspended | not disclosed |
| `person-enrolment-ambiguous` | `org-active` | Ambiguous | not disclosed |
| `person-ambiguous` | `org-active` | Not reached | Person record fails first |
| `person-timeout` | `org-active` | Not reached | Person record fails first |
| `person-unenrolled` | | None | |
| `person-active` | `org-other` | None | |

`membership` on an active enrolment returns `person_id`, `organisation_id` and `roles`. An empty role list is returned as-is.

`enrolment` on an active enrolment returns `person_id`, `organisation_id` and `status = active`. Suspended returns nothing and fails closed `suspended_enrolment`. An ambiguous enrolment fails closed `ambiguous_status`. No link fails closed `not_enrolled`.

`lookup_mandate` uses the same enrolment checks. When the enrolment is active, `granted` is true only if the role string is one of the fixture roles. `lms.campaign.write` is not on `person-active`, so that lookup returns `granted: false`.

The role names in the directory are fixtures. They are not a complete role catalogue.

## Booking freeze

Request to `identity_for_booking`: `person_id`.

Response for `person-active`:

```text
person_id: person-active
name: Test Consumer
id_number: 0000000000000
service_address: 1 Dummy Street, Johannesburg
```

`freeze_booking_identity` then returns:

```text
name: Test Consumer
id_number: 0000000000000
service_address: 1 Dummy Street, Johannesburg
```

The frozen value is a copy taken at that call. The agreement stores the copy. A later read of Enigma is not written back onto it.

If the name or ID number on a decision-engine application differs from this read, which one is frozen is not locked. The dummies do not compare them.
