# LMS test deployment

The application on this branch is the latest one that already has the staff UI, sequential loan numbers, and the decision-engine and debit-order stubs: `cursor/close-d4-agreement-fields-1ace`. Later loan-number branches do not contain the stubs, so they are not the base.

Region is `us-east-1`, the region already used by the Enigma account. The stack is one tenant, for testing. It does not seed an election. A missing election or a missing reference row fails closed. Identities used in the exercise are synthetic. A test NCR number, when a compliance row is saved, is one you type (for example `NCRCP999999`). No production data is loaded.

## What the stack creates

`cloudformation.yml` creates:

- RDS PostgreSQL `db.t4g.micro`, engine 16.4, private, single-AZ. Aurora Serverless is not used: the micro instance is the smaller always-on database for this low-traffic test.
- ECS Fargate (`lms-test`, 0.25 vCPU, 512 MB) running this image. The container applies `db/migrations` and `db/seed/001_reference.sql` on start, then serves.
- An internet-facing load balancer on port 80.
- A private S3 bucket for statement artifacts and brand assets.

`task-definition.json` is the same container contract (image, port 8765, environment, database secret, logs, health check). CloudFormation is what creates the running task definition. Replace `ACCOUNT_ID` only if you register the JSON yourself.

The container command is `deploy/aws/entrypoint.sh`: migrate, then `python -m lms.staff_ui`. The reference seed ignores an audit-event code that migration 0010 or 0011 already inserted, so the seed can run after every migration. The stored code and category are unchanged.

Servicing state for the staff screens and the exercise stays in the process, which is how this branch already runs. The database receives the existing schema and the statutory reference seed. It does not receive a copied election.

## Public URL

Not issued. The IAM user `Eugene_Ehlers` in account `026465780614` cannot create the stack. The calls that were refused are `rds:CreateDBInstance`, `ecs:CreateCluster`, `elasticloadbalancing:CreateLoadBalancer`, `ecr:CreateRepository`, `s3:CreateBucket`, `iam:CreateRole`, and `cloudformation:ValidateTemplate`.

A principal that has those permissions creates the environment with:

```bash
./deploy/aws/up.sh
```

The script prints the stack outputs. Open:

| Output | Path |
| --- | --- |
| `PublicUrl` | `/staff/` |
| `ExerciseUrl` | `/exercise` |
| `ConsumerRegistrationUrl` | `/self/register` |
| `HealthUrl` | `/health` |

The load balancer speaks HTTP. There is no domain certificate in this test stack.

## Login

Enigma is not connected, and no Enigma page address is configured, so the consumer pages do not redirect to an invented URL.

- Staff bypass: `/staff/`. Submit the opaque person id, organisation id, role names, and Enigma status. There is no email field and no password. This is the temporary bypass.
- Consumer registration: `/self/register`.
- Consumer sign-on: `/self/sign-on`. A POST is refused. The screen does not accept those details.
- Stored statement: `/self/statement`. It stays closed until the session has an active person and organisation. It does not issue a statement.
- Settlement quote: `/self/settlement-quote`. Same gate. This deployment does not hold a quote, so the open page says none is stored.

## Booking and a payment

`/exercise` calls `DecisionQuoteStub`, then `Servicing.book` and `Servicing.disburse`, then the sequential loan-number series. The debit-order section calls `DebitFileStub` and `Servicing.accept_payment`. Leave an election blank and the call stops. The page does not choose a rate.

One synthetic booking that the current engine accepts:

| Field | Value |
| --- | --- |
| Organisation id | `org-test` |
| Person id | `person-test-001` |
| Full name | `Test Consumer` |
| Identity number | `0000000000000` |
| Service address | `1 Dummy Street, Johannesburg` |
| Idempotency key | `book-test-1` |
| Product | `micro_short_term` |
| Frequency | `monthly` |
| Cash advanced, cents | `100000` |
| Schedule due date | `2026-06-15` |
| Schedule amount, cents | `100000` |
| Recognised at | `2026-03-01T08:00:00+02:00` |
| Disbursed at | `2026-03-01T10:00:00+02:00` |
| Leniency days | `1` |
| Full payment threshold percent | `100` |
| Interest on deferred initiation | `none` |
| Repo-rate fall | `contract_rate` |
| Day count | `actual_actual` |
| VAT on rand maxima | `exclusive` |
| Late disbursement | `keep_instalment` |
| Partial prepayment | `shorten_term` |
| In-duplum trigger | `collections_default` |

Then, on the debit-order form, use the agreement id from the result, amount `10000` cents, due date `2026-06-15`, recognition date `2026-03-20`, and outcome `success`.

Statement artifacts are stored under `statements/{organisation}/{statement id}.json`. The body is the stub payload the statement issuer already returns. Set `interest_cap_present` to `true` only when a cap row covers the value date, and supply `vat_rate` (the smoke tests use `0.15`). A blank cap, `false`, or a blank VAT rate fails closed and nothing is uploaded. Brand assets are stored under `brand/{organisation}/{asset name}`. Both fail closed when the bucket is not configured. `LMS_REQUIRE_DEPLOY_CONFIG=1` also refuses to start when the bucket, the database settings, or the reference seed is missing.

## Tear down

```bash
./deploy/aws/down.sh
```

That empties the statement bucket, deletes the `lms-test` stack (VPC, database, load balancer, cluster, roles, secret, log group), and deletes the `lms-test` ECR repository. The database is not snapshotted.
