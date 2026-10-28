# LMS port on Enigma

Updated 27 October 2026 (Africa/Johannesburg), after `docs/LOCKED_DECISIONS.md` landed on main at 22:10 (Africa/Johannesburg) in commit `d19f4ea`.

This is the interface the post-origination LMS needs from Enigma, plus the LMS-side session handling that sits on it. Calculation, ledger, and servicing rules are not restated here. They live in `docs/LOCKED_DECISIONS.md`, which is the single source of truth. This document does not change those rules.

`src/lms/enigma/` implements this port. HTTP paths stay unbound: `UnboundHttpEnigmaPort` and `UnboundMachineIdentity` raise `UnboundEnigmaPort` and do not invent a URL. Conflicts C1–C10 stay open. This code does not close them and does not store provider choices, tariffs, or leniency.

The implementation note is `docs/enigma/IMPLEMENTATION_NOTE.md`. The checklist is `docs/enigma/LAYER1_IMPLEMENTATION_CHECKLIST.md`.

## Behaviour citations

Each implemented behaviour names the locked section that governs it. "No section" means the locked file does not say it. Those rows are the conflicts, not new rules.

| Behaviour | Locked section |
| --- | --- |
| Enigma owns identity, organisations, memberships, enrolment, roles, and mandates | 15 |
| LMS keeps opaque `person_id` and `organisation_id` | 15 |
| Fail closed on timeout or an ambiguous status | 15 |
| Freeze name, ID number, and service address at booking | 16 |
| A later Enigma change does not rewrite that agreement | 16 |
| Clear `suspended` enrolment stops the request, including a read | No section. Port decision 3. Conflict C3. Section 15 covers timeout and ambiguous status only |
| Organisation switch and cookie generation `409` | No section. Port mechanic in this design |
| Allocation member may run only `lms.allocation.run`. Write-off is `mandate_denied` | No section. Port decision 2. Conflict C9. Section 15 still owns mandates |
| IAM task-role exchange | No section. Port decision 2. The HTTP exchange raises `UnboundEnigmaPort` |
| Live email, mobile, and preferred channel | No section. Port decision 6. Conflict C10. Section 16 names three fields |
| NCR number and operational rand ceilings | No section. Port decisions 4 and 5. Conflict C2 |
| Value date at 00:00 | 1. Not applied to the Enigma session clock. Conflict C7 |
| Unset leniency or full-payment threshold fails closed | 6. This port does not store those fields. Conflict C6 |
| In-duplum clip stays off | 7. This port does not turn it on |
| Section 126 order | 8. Not an Enigma response |
| One statement per client | 12. Conflict C5 with the per-account action name |
| Missing repo-rate choice fails closed | 11. This port does not choose option A or B |
| Missing tariff row fails closed | 18. This port does not invent a tariff |
| Billing round half-up to cents | 17. Not applied to the operational ceiling |

## What the locked file changes in this port

Each row is a consequence for the Enigma port, or an explicit "no port change". No row adds a rule that `docs/LOCKED_DECISIONS.md` does not already contain.

| Locked section | Effect on this port |
| --- | --- |
| 1. Value date is 00:00 on the system recognition date | No change to the Enigma session clock. Authority is still the result of the live call. The value date of a posting is an LMS fact. Whether a mandate is judged at 00:00 is not stated. See conflicts. |
| 2. Initiation fee capitalised or due under section 126 | No port change. The port does not choose capitalisation. |
| 3. Zero rates, zero fees, campaigns | No port change. The port does not store a campaign rate. |
| 4. Laybye linked to a loan is one loan, parent/child, not security that would make the loan secured | The sketch code `lms.laybye_security` uses the word "security". That name is not in the locked file. See conflicts. Death, funeral, credit life, and section 124 are not Enigma calls in the locked file. |
| 5. Day count is the credit provider's choice. Actual/actual is the recommendation for new products. 30/360 stays selectable. Accrual is daily. A 360-day year is not required for Day-1 | No port operation returns a day-count convention. Where the choice is stored is not stated. See conflicts. |
| 6. One default definition. Leniency and the full-payment threshold are per customer. Unset values fail closed. Example numbers must not be hard-coded as defaults | No Enigma field for `leniency_days` or `full_payment_threshold_percent` is named. The sketch must not supply 4, 5, or 95 as defaults. See conflicts. |
| 7. In-duplum episodes. Three section 103(5) edges stay unsigned and the clip stays off until counsel confirms | No port change. The port does not turn the clip on. |
| 8. Section 126 order | No port change. `lms.allocation.run` only asks whether the actor may run allocation. The order is not an Enigma response. |
| 9. Service-fee pro-rata and VAT | No port change. Rand maxima and the VAT election are not Enigma fields in the locked file. |
| 10. Interest on a deferred initiation fee is a provider choice. Default in the locked file is no interest. The alternative is permitted. Stored per organisation or per product | The port does not store this choice. "Per organisation or per product" has no table in the locked file. See conflicts. |
| 11. Rate after the repo rate falls is a provider choice. No platform default. Fail closed until the provider chooses. Stored per organisation or per product | Same storage gap as section 10. The port must not fill a missing choice with option A or option B. |
| 12. One statement per client, all loans | The sketch action `lms.account.statement.read` is named per account. The locked rule is per client. See conflicts. |
| 13. External decision engines must be accepted long-term. Instalment choices, restructure, and a further monthly fee are LMS behaviour. "Subsequent" short-term loan is counted per credit-provider organisation | The count key is `organisation_id`. The port does not define the counter. |
| 14. Weekly, fortnightly, monthly, quarterly, bi-annual, and annual frequencies | No port change. |
| 15. Enigma owns person identity, organisations, memberships, product enrolment, roles, and mandates. LMS stores only opaque `person_id` and `organisation_id`. LMS does not re-implement person or organisation identity. Fail closed on Enigma timeout or ambiguous status | This is the port boundary. It is repeated under Fixed LMS rules. It conflicts with other sentences in the same locked file and with port decisions 4 and 5 below. See conflicts. |
| 16. Freeze name, ID number, and service address at booking. Later Enigma changes do not rewrite the concluded agreement | Already the identity-freeze section below. The three fields are the whole freeze. |
| 17. Round half-up to cents on billing. Disclose the annual equivalent rate. The same rounding rule everywhere it is required. Rounding must not push an instalment above the affordability figure already aligned with the client | No port change. The sketch's ceiling comparison is integer cents and is not a billing round. Section 17 does not say to round the operational ceiling. |
| 18. Default-administration and collection-cost tariffs fail closed until a tariff row exists | The port does not invent a tariff. A missing row stops the charge. The locked file does not say Enigma holds the tariff. |

## Port decisions recorded in this design

These six points were recorded in this design on 27 October 2026 from the Enigma brief. Points 1, 3, and 6 overlap the locked file. Points 2, 4, and 5 are not sentences in `docs/LOCKED_DECISIONS.md`. They are not deleted here. They are not promoted into that file by this document. The overlap and the absence are in the conflicts list.

### 1. Staff boarding follows the Academy pattern

Enigma owns the organisation and its staff list, including roles and mandates. An admin role amends that list in Enigma. Human sign-on is Cognito, fronted by Enigma. LMS trusts the membership and the role Enigma returns on `membership.validate` and the allow or deny from `mandate.lookup`.

LMS does not keep a staff table that can grant access. LMS does not amend the list. The next request after an admin change sees the new membership because every request asks Enigma again.

A person operates only in organisations where that answer is an active membership with at least one role. An active membership with an empty role list is ambiguous and stops the request.

### 2. Machines use an IAM role, exchanged by Enigma

Human path: Cognito authenticates the person, Enigma maps them to membership and roles.

Machine path: the job's AWS IAM role authenticates the process, Enigma maps the role ARN to a machine member, and the same five operations run with that machine session. The machine's allowed actions are a short list on the Enigma registration. Allocation is `lms.allocation.run`. A write-off call from that job is denied by `mandate.lookup`.

Comparison and the rejected alternatives are in [Machine identity](#machine-identity).

### 3. Suspended or unclear means stop

Servicing reads and money movement both stop unless sign-in, organisation status, membership, role, and enrolment are each a clear active answer, and `mandate.lookup` is a clear allow for the declared action.

`suspended`, `absent`, `closed`, a timeout, an HTTP 5xx, an unknown status, a missing role, or an enrolment answer for a different product all stop the request. Nothing in that set falls through to a cached role.

### 4. NCR number lives in LMS

Enigma does not hold the credit provider's NCR number. LMS stores it as a tenant regulatory attribute.

It is required later, on NCA compliance extracts and on communications for products that fall under the NCA. For the day-1 catalogue that means `lms.micro_short_term` and `lms.unsecured_personal`, unless the tenant is marked pure hosting. It is not required for pure hosting, `lms.bnpl_laybye`, or `lms.laybye_security`.

A blank number refuses the NCA communication or extract. It does not refuse booking. `ncr_number_required` in `src/lms/enigma/regulatory.py` is the gate.

### 5. Rand ceilings are adjustable data, evaluated by LMS

These are operational ceilings (for example a write-off ceiling). They are not the statutory NCA maxima. Those stay in the calculation engine.

- TSDG, the platform owner, adjusts solution-wide ceilings through an interface. The actor must hold Enigma role `lms.ceiling.platform.write` in the platform organisation.
- A company adjusts its own ceilings through an interface. The actor must hold Enigma role `lms.ceiling.company.write` in that company. The platform organisation cannot use the company screen to write a company's row.
- LMS stores the amounts. The next command reads the current rows. No deploy is required.
- The effective ceiling is the platform amount, or the lower of the platform and company amounts when the company has set one. A company figure above the platform ceiling does not raise the limit.
- A missing platform ceiling, a non-ZAR currency, or a negative amount is ambiguous and stops the command.
- An amount equal to the limit is inside the ceiling. One cent over is `mandate_denied`.

Role strings above are port names. The adapter maps them to Enigma's real role ids. See the remaining-details list.

Worked example. Platform write-off ceiling R10 000. Cape Credit sets R1 000. A clerk whose Enigma role allows `lms.account.write_off` submits R1 500 (`amount_cents` 150000). `mandate.lookup` returns allow. LMS then applies the ceiling and denies. R1 000.00 (`amount_cents` 100000) is allowed. If Cape Credit instead saves R50 000, the effective ceiling stays R10 000 until TSDG raises the platform row.

### 6. Identity freeze at booking

At booking LMS reads the live Enigma person and snapshots three fields onto the agreement: name, ID number, and service address. A later change in Enigma does not rewrite that agreement. A correction is a new LMS command with a new snapshot.

Communication preferences (email, mobile, preferred channel) are read from the live Enigma person at send time. They are not part of the frozen agreement.

A blank name, ID number, or service address refuses booking (`attributes_unavailable`). The booking command is not committed.

Worked example. Thandi is booked at 10:00 Africa/Johannesburg as "Thandi Nkosi", ID number `8001015009087`, service address "12 Loop Street, Cape Town". She later changes her name and address in Enigma. The concluded agreement still shows Loop Street. A statement email uses the email address on the live record.

## Fixed LMS rules

These follow `docs/LOCKED_DECISIONS.md` sections 15 and 16. Cognito, the cookie, and the audience check are port mechanics from this design. They are not new locked rules.

1. Enigma is the registry for persons, organisations, memberships, product enrolment, roles, and mandates. LMS stores opaque `person_id` and `organisation_id`. LMS does not re-implement person or organisation identity. The agreement freeze in section 16 of the locked file is the named exception for name, ID number, and service address. Cognito is the human authenticator in this design. The locked file does not name Cognito.
2. The browser receives an LMS cookie (`HttpOnly`, `Secure`, `SameSite`). The Enigma session reference stays on the server. Production storage encrypts it at rest. The in-memory store in the sketch does not.
3. A session whose audience is not `lms` does not open an LMS session. The I-DIP audience `product-idip` is the case already seen in a sibling product.
4. Every request introspects the session. The route declares an action and, except for an organisation switch, a product code. A missing action or product is ambiguous.
5. Events clear caches. An event never grants a permission.
6. Timeout, HTTP 5xx, and an unrecognised payload become `authority_unavailable` or `authority_ambiguous`. The command is not committed.
7. After the caller may act in the active organisation, an account in another organisation is answered the same way as a missing account.
8. Timestamps from Enigma are absolute instants. LMS displays them in Africa/Johannesburg.

## Who owns which fact

Rows for the NCR number, operational ceilings, the legal-name projection, and the session reference are port decisions in this design. Locked section 15 does not list them. See conflicts C1 and C2. The freeze row is locked section 16.

| Fact | Authority | What LMS keeps |
| --- | --- | --- |
| Person identifier | Enigma | Opaque `person_id` on the account and the audit row |
| Name, ID number, service address | Enigma at booking | Frozen `AgreementIdentity`. Not updated from later Enigma reads |
| Email, mobile, channel preference | Enigma, live | Nothing on the agreement. Read again when sending |
| Organisation identifier | Enigma | Tenant key on every LMS row |
| Legal name, trading name | Enigma | Header projection |
| NCR number | LMS | Tenant regulatory attribute. Blank blocks NCA communications and extracts only |
| Staff list, roles, mandates | Enigma | Mandate id and version on the command snapshot. No staff table |
| Operational rand ceilings | LMS values, Enigma role gate | Platform row and per-company row, with versions on the snapshot |
| Product enrolment | Enigma | Menu cache only. Account routes call `enrolment.check` |
| Session | Enigma, after Cognito | LMS session id, session reference, person id, active organisation, generation |
| Loans, balances, allocation, settlement maths | LMS | Servicing record |

### Authority snapshot

Written in the same transaction as a regulated command that commits.

| Field | Meaning |
| --- | --- |
| `command_id` | LMS command |
| `person_id` | Actor, or the machine id Enigma returned |
| `organisation_id` | Active tenant |
| `session_ref_hash` | Hash of the Enigma session reference |
| `action` | For example `lms.account.write_off` |
| `product_code` | Enrolment code |
| `mandate_id`, `mandate_version` | From a clear allow |
| `enrolment_id`, `enrolment_version` | From a clear active enrolment |
| `platform_ceiling_version`, `company_ceiling_version` | Present when an amount was checked. Company version is empty when the company has not tightened the platform ceiling |
| `enigma_request_id` | Correlation id |
| `decided_at` | Instant of the decision |

A later revocation leaves the snapshot in place. Retention follows the audit record. The retention period is still a compliance decision and is not set here.

### Session row

| Field | Meaning |
| --- | --- |
| `lms_session_id` | Cookie name |
| `session_ref` | Enigma reference. Server only |
| `person_id` | Actor |
| `active_organisation_id` | Tenant currently selected |
| `organisation_generation` | Increments when the active organisation changes. A mismatch is HTTP 409 |

Switching to the organisation that is already active does not increment the generation, so other tabs stay valid.

## Port operations

Python: `EnigmaClient` in `src/lms/enigma/client.py`. The five methods are the port. They are not yet Enigma URLs.

Every call takes a `request_id`. Decisions carry `enigma_request_id`.

### `introspect(session_ref, *, request_id) -> SessionView`

Locked section 15: an ambiguous status fails closed. `session.introspect`. LMS proceeds only when `audience == "lms"`, `status == "active"`, `sign_in_clear` is true, and `person_id` is present. Expired or revoked, or a foreign audience, is `reauthenticate` (401). Any other shape is `authority_ambiguous` (503). The audience string `lms` is not in the locked file.

`bound_organisation_id`, when set, must match the organisation LMS is about to use. A mismatch is ambiguous. LMS calls `session.bind_organisation` only if Enigma's real introspect includes that field. The method is not in the five.

### `organisation_context(session_ref, organisation_id, *, request_id) -> OrganisationContext`

Locked section 15: the organisation stays in Enigma. Proceeds only for `status == "active"` on that organisation id. `suspended` and `closed` are `organisation_unavailable` (403). Anything else is `authority_ambiguous` (503), which is the locked fail-closed for an ambiguous status.

### `validate_membership(session_ref, person_id, organisation_id, *, request_id) -> Membership`

Locked section 15: membership, roles, and mandates stay in Enigma. Proceeds only for `status == "active"` and a non-empty `roles` tuple. `suspended` and `absent` are `not_a_member` (403). An active membership with no role is `authority_ambiguous` (503). LMS does not map a local role table.

### `lookup_mandate(query, *, request_id) -> MandateDecision`

Locked section 15: the mandate decision comes from Enigma. `query` carries session, person, organisation, action, and product code. `allow` with a mandate id and version is the only yes, and only for that action. `deny` is `mandate_denied` (403). Any other payload is `authority_ambiguous` (503).

Rand ceilings are not decided here. After a clear allow, LMS calls `enforce_amount` when the command has an amount.

Day-1 actions:

| Action | Who |
| --- | --- |
| `lms.account.read` | Staff |
| `lms.account.statement.read` | Staff |
| `lms.account.open` | Staff, at booking |
| `lms.payment.capture` | Staff |
| `lms.allocation.run` | Machine member |
| `lms.settlement.quote` | Staff. Arithmetic is LMS |
| `lms.settlement.accept` | Staff |
| `lms.account.write_off` | Staff, then the rand ceiling |
| `lms.account.restructure` | Staff |
| `lms.party.attributes.read` | Staff, to freeze or to read live preferences |
| `lms.export.borrower_data` | Staff |
| `lms.ceiling.platform.write` | TSDG role, platform organisation only |
| `lms.ceiling.company.write` | Company role, that company only |

### `check_enrolment(session_ref, organisation_id, product_code, *, request_id) -> Enrolment`

Locked section 15: product enrolment stays in Enigma. Proceeds only for `status == "active"` on the requested product code, with an enrolment id. A clear `suspended` or `absent` is `enrolment_denied` (403), including on a read. That stop is port decision 3. Section 15 does not name a clear `suspended` status (conflict C3). A different product code, or any other status, is `authority_ambiguous` (503) under section 15.

Proposed codes, still to be confirmed against Enigma's catalogue:

| Code | Day-1 product | NCR number on communications |
| --- | --- | --- |
| `lms.micro_short_term` | Micro / short-term | Required when the tenant is not pure hosting |
| `lms.unsecured_personal` | Unsecured personal | Required when the tenant is not pure hosting |
| `lms.bnpl_laybye` | BNPL / laybye, zero cost | Not required |
| `lms.laybye_security` | Laybye as zero-interest security or deposit | Not required |

Enrolment and role are both required. A director role does not enrol the organisation.

## Identity freeze

Locked section 16. `freeze_at_booking` in `src/lms/enigma/identity_freeze.py` reads the live Enigma person and returns an `AgreementIdentity` with `person_id`, `name`, `id_number`, and `service_address`. There is no function that writes those three fields again. `frozen_at` and `source_request_id` are technical columns and are not named in section 16.

`communication_preferences` reads the same live person and returns email, mobile, and preferred channel. Callers must not write those fields onto the agreement.

Timeout and HTTP 5xx on the read are `authority_unavailable`. Booking waits.

## Session middleware

`src/lms/enigma/middleware.py`. Locked section 15: every request introspects Enigma, and a timeout or an ambiguous status fails closed (`authority_unavailable` or `authority_ambiguous`). The cookie generation and the 409 are port mechanics. The locked file does not name them.

`establish_session` runs after the Cognito/Enigma callback. It introspects, checks organisation and membership, and stores generation `1`.

`handle_request` on every later call:

1. Load the LMS session. A missing cookie is 401.
2. `introspect`. Timeout or 5xx is 503 `authority_unavailable`. Unclear sign-in is 503 `authority_ambiguous`.
3. Compare the cookie generation to the server session. A mismatch is 409 `organisation_context_stale`, with the current organisation id and generation, and the loan is not read.
4. Organisation switch, when asked: `organisation_context` and `validate_membership` for the target. On success the generation increments and the cookie must be replaced. A stale tab cannot switch.
5. Otherwise require a product code, an active organisation, an active membership with a role, an active enrolment, and a mandate allow. An amount then goes through `enforce_amount`.

The edge returns `HttpResult`. Enigma response bodies stay in the server log beside `enigma_request_id`.

## Machine identity

Allocation and other non-human jobs have no staff cookie. Four patterns:

| Pattern | Authentication | How the mandate is limited | Credential on the job | Verdict |
| --- | --- | --- | --- | --- |
| Enigma + AWS IAM | The task role presigns `sts:GetCallerIdentity`. Enigma verifies it with AWS and returns a machine session | Enigma machine member lists the actions. LMS then calls the same `lookup_mandate` and `check_enrolment` | No long-lived access key. The role is the identity | Recommended. Same shape as Enigma + Cognito for humans |
| Cognito client credentials | App client id and secret. Enigma maps the client to a machine member | Same Enigma action list | Long-lived secret | Simpler only while Enigma cannot verify IAM. Interim: secret in Secrets Manager, rotation, private subnet. Not the target |
| Network location or mTLS only | Being inside the VPC, or holding a client certificate | No per-action mandate | Certificate | Rejected for allocation. Any process on that network could call write-off |
| Copied staff session | A person's Enigma session stored for the job | Whatever that person can do, including after they leave | The session | Rejected |

### Recommended registration

The machine list lives in Enigma and is amended by the same admin role that amends the staff list. LMS does not store a second copy. `MachineRegistration` in `src/lms/enigma/models.py` is the record Enigma holds.

1. Create an IAM role, for example `lms-allocation-cape-credit`, trusted only by the ECS task or Lambda service. No human principal. No access keys.
2. An Enigma admin adds a machine member: display name, `organisation_id`, IAM role ARN, AWS account, and allowed actions. For the nightly allocation job the list is `{lms.allocation.run}`.
3. The job runs as that task role. It presigns `GetCallerIdentity` and passes the proof to LMS.
4. LMS calls `MachineIdentityPort.exchange`. Enigma checks the signature, the role ARN, and the machine member, and returns a session reference.
5. LMS runs `introspect`, `organisation_context`, `validate_membership`, `check_enrolment`, and `lookup_mandate` for `lms.allocation.run`. Unclear answers fail closed and the batch posts nothing.
6. Removing the machine member, or deleting the IAM role, stops the next run. `handle_machine_request` returns `mandate_denied` for any action other than `lms.allocation.run`, including `lms.account.write_off`, even when `lookup_mandate` would have returned allow. That limit is port decision 2. Locked section 15 does not describe the job (conflict C9).

`UnboundMachineIdentity.exchange` raises `UnboundEnigmaPort`. The presigned URL is the proof. LMS does not mint keys and does not verify AWS itself. Locked section 15 does not name this exchange.

Worked example. At 02:00 Africa/Johannesburg the Cape Credit allocation job exchanges its task role. Enigma returns a machine session whose only action is `lms.allocation.run`. The job allocates. A remainder that the job tries to write off is `mandate_denied`. If the exchange times out, the run is `authority_unavailable` and posts nothing.

## Sequences

### Login

```mermaid
sequenceDiagram
  actor Staff
  participant Cognito
  participant Enigma
  participant LMS
  Staff->>Cognito: Sign on
  Cognito-->>Enigma: Authenticated person
  Enigma-->>LMS: Callback with session reference
  LMS->>Enigma: introspect
  alt Audience is not lms, or session is not active
    LMS-->>Staff: 401 reauthenticate
  else Sign-in flag unclear
    LMS-->>Staff: 503 authority_ambiguous
  else One clear organisation
    LMS->>Enigma: organisation_context and validate_membership
    LMS-->>Staff: LMS cookie, generation 1
  else Several organisations
    LMS-->>Staff: Picker
    Staff->>LMS: Chosen organisation
    LMS->>Enigma: validate_membership for that organisation
    LMS-->>Staff: LMS cookie, generation 1
  end
```

### Organisation switch

```mermaid
sequenceDiagram
  actor Staff
  participant LMS
  participant Enigma
  Staff->>LMS: Switch to org_b, cookie generation 1
  LMS->>Enigma: introspect
  alt Timeout or 5xx
    LMS-->>Staff: 503 authority_unavailable. Organisation unchanged
  else Cookie generation is not 1
    LMS-->>Staff: 409 organisation_context_stale
  else Membership in org_b is active and has a role
    LMS-->>Staff: Cookie generation 2, active organisation org_b
  else Membership unclear
    LMS-->>Staff: 403 or 503. Generation stays 1
  end
  Staff->>LMS: Tab still on generation 1
  LMS-->>Staff: 409. Loan is not read
```

Worked example. Johan is a member of North Bridge (`org_a`) and Harbour (`org_b`). He switches to Harbour at 11:00 Africa/Johannesburg. Generation becomes 2. A North Bridge tab still presenting generation 1 receives 409. After the browser retries with generation 2, a North Bridge loan id is answered as not found.

### Write-off

```mermaid
sequenceDiagram
  actor Staff
  participant LMS
  participant Enigma
  Staff->>LMS: Write off R1 500
  LMS->>Enigma: introspect, membership, enrolment, mandate.lookup
  alt Enigma role denies the action
    LMS-->>Staff: 403 mandate_denied
  else Enigma allows, ceiling is not a clear ZAR pair
    LMS-->>Staff: 503 authority_ambiguous. Not committed
  else Enigma allows, amount is inside the tighter ceiling
    LMS-->>Staff: Commit command, snapshot mandate and ceiling versions
  else Enigma allows, amount is over the tighter ceiling
    LMS-->>Staff: 403 mandate_denied. Not committed
  end
```

## Errors

The adapter maps Enigma's codes onto these. `HttpResult.error` is the code.

| Code | HTTP | When |
| --- | --- | --- |
| `reauthenticate` | 401 | Missing session, expired, revoked, or audience other than `lms` |
| `not_a_member` | 403 | Membership `absent` or `suspended` |
| `organisation_unavailable` | 403 | Organisation `suspended`, `closed`, or a different id |
| `enrolment_denied` | 403 | Enrolment `absent` or `suspended`, on reads and on mutations |
| `mandate_denied` | 403 | Lookup `deny`, or amount over the effective ceiling, or a ceiling edit without the role |
| `organisation_context_stale` | 409 | Cookie generation does not match. Body includes the current organisation and generation |
| `attributes_unavailable` | 409 | Booking is missing name, ID number, or service address, or a send has no live channel |
| `authority_unavailable` | 503 | Timeout, HTTP 5xx, or connection failure. Command not committed |
| `authority_ambiguous` | 503 | Unclear sign-in, empty role, unknown status, missing platform ceiling, or a payload the client does not recognise |
| `wire_unbound` | 503 | The placeholder adapter was called |

`introspect`, `organisation_context`, `validate_membership`, `lookup_mandate`, and `check_enrolment` are safe to retry with the same `request_id`.

Cache rules: session, membership, mandate, and enrolment authorise only inside the request that fetched them. A menu may show a stale action. The command calls lookup again. A negative cache is not used.

## LMS modules

| Module | Responsibility |
| --- | --- |
| `src/lms/enigma/client.py` | Five operations and fail-closed mapping |
| `src/lms/enigma/errors.py` | Error types and HTTP statuses |
| `src/lms/enigma/models.py` | Port value types, including the Enigma-held `MachineRegistration` |
| `src/lms/enigma/port.py` | `EnigmaPort`, `PersonDirectory`, `MachineIdentityPort`, `UnboundEnigmaPort` |
| `src/lms/enigma/middleware.py` | Establish session, switch, generation 409, per-request introspect |
| `src/lms/enigma/identity_freeze.py` | Booking snapshot and live communication preferences |
| `src/lms/enigma/ceilings.py` | Role gate for edits, tighter-of platform and company |
| `src/lms/enigma/machine.py` | Unbound IAM exchange |
| `src/lms/enigma/regulatory.py` | Whether an NCR number is required for a communication |
| `tests/test_enigma_session.py` | Session, freeze, ceiling, and NCR behaviour |

`python3 -m pytest tests/test_enigma_session.py` covers the draft sketch. It does not certify `docs/LOCKED_DECISIONS.md`. There is no UI in this change.

## Conflicts and technical gaps

Nothing in this section chooses a winner. `docs/LOCKED_DECISIONS.md` is the source of truth. Closing a row means editing that file, not this one.

| # | What is in tension | Why it is unresolved |
| --- | --- | --- |
| C1 | Locked section 15 says LMS stores only opaque `person_id` and `organisation_id`. Locked section 16 requires the agreement to keep name, ID number, and service address | Both sentences are locked. This design keeps the freeze because section 16 names those fields. It does not treat section 15's "only" as deleting section 16 |
| C2 | This design's port decision 4 stores the NCR number on the LMS tenant. Port decision 5 stores operational rand ceilings on the LMS. The session row stores an Enigma session reference. The authority snapshot stores mandate and enrolment ids. A header projection stores legal name | None of those stores are listed in locked section 15. This design does not remove them and does not add them to the locked file |
| C3 | This design stops a clear `suspended` or `absent` enrolment, including on a read. Locked section 15 fails closed on timeout or ambiguous status | A clear `suspended` is not an ambiguous status. The broader stop is a port decision in this design. The locked file does not say it |
| C4 | Sketch product code `lms.laybye_security` | Locked section 4 says the linked Laybye is not security that would make the loan secured. The code is a sketch name. This document does not rename it |
| C5 | Sketch action `lms.account.statement.read` | Locked section 12 is one statement per client for all loans. The action name is per account. This document does not invent a replacement action |
| C6 | Locked sections 5, 10, and 11 store a provider choice per organisation or per product. Locked section 6 stores leniency and a threshold per customer | The locked file does not say whether those rows are LMS rows keyed by an opaque id, or Enigma attributes. This design does not create the tables |
| C7 | Locked section 1 fixes the value date at 00:00 on the recognition date | It does not say the Enigma session, the mandate, or Cognito expiry moves to 00:00. The live authority call stays on its own clock until that is written into the locked file |
| C8 | Locked section 4 names a beneficiary, credit life, funeral benefit, and a section 124 authority | It does not say the beneficiary is an Enigma `person_id`, or that the section 124 authority is an Enigma document. This design does not add those calls |
| C9 | Port decision 2 (IAM machine exchange) and the staff-list admin role | Not stated in the locked file. Left in this design as port decisions. Not treated as section 15 wording |
| C10 | Port decision 6 also reads email, mobile, and preferred channel from the live Enigma person at send time | Locked section 16 names only name, ID number, and service address. The preference read is not a locked sentence. This design does not add it to the freeze |

## Remaining Enigma API details

These are the unread Enigma wire details from `STATUS.md`, the architecture docs, `consumer_contract.py`, the identity registry, mandates, and sessions. They are separate from conflicts C1–C10. Closing C1–C10 is an edit to `docs/LOCKED_DECISIONS.md`, not a guess at these paths.

1. HTTP paths, how LMS authenticates as a consumer, and the error-code map.
2. Cognito callback shape. LMS expects a session reference. Confirm whether the callback is that reference or an authorization code to exchange, and the claim that carries audience `lms`.
3. Real role ids for staff admin, `lms.ceiling.platform.write`, and `lms.ceiling.company.write`.
4. IAM exchange. The request Enigma will accept (presigned `GetCallerIdentity` or another SigV4 call), the checks on account and role ARN, and the machine session reference it returns.
5. Live person field names for name, ID number, service address, email, mobile, and preferred channel.
6. Whether `session.introspect` returns `bound_organisation_id`. If it does, switch must call Enigma's bind operation and LMS must not keep a local organisation the session is not bound to.
7. Catalogue strings for the four product codes.
8. Event signature, delivery, and the tombstone event if a person can be closed. A tombstone clears display projections and does not delete frozen agreement identity or authority snapshots.
9. Sandbox versus production audience, so a sandbox session cannot introspect into a production organisation.
10. How the admin staff-list screen is reached. LMS does not implement the amendment. Confirm whether the UI deep-links into Enigma or calls an Enigma API.

## Out of scope

Calculation, the ledger, and servicing behaviour are specified in `docs/LOCKED_DECISIONS.md`. This port does not restate them and does not fill a gap in them.

LMS does not register persons, does not register organisations, and does not edit the staff list or machine list. Those last two sentences are port decisions in this design. Locked section 15 does not name the staff-list editor.
