# Merged smoke results

Run on 28 October 2026 against `cursor/merged-smoke-ccde`. Amounts are integer cents. Recognition instants are 00:00 Africa/Johannesburg. The test is `tests/test_merged_smoke.py`. Locked decisions were not changed. Existing open issues were not closed.

The decision engine, debit-order rail, and Enigma dummies were called. Servicing still posts through `EnigmaStub.check`, because that is the check `Servicing.book` makes. The smoke copied the dummy's booking identity onto that stub before booking, so the frozen name is the dummy's.

## Dummies

| Call | Result |
|------|--------|
| `EnigmaDummy.identity_for_booking("person-active")` | Test Consumer, ID `0000000000000`, 1 Dummy Street, Johannesburg |
| `EnigmaDummy.organisation.context("org-active")` | Company registration `2020/000000/07` |
| `EnigmaDummy.session.introspect("session-active")` | `person-active` |
| `EnigmaDummy.lookup_mandate(..., "lms.collection_campaign.write")` | `granted=False` |
| `DecisionEngineDummy.fixed_success(500 bps)` | Approval rate 500 bps. Term and frequency are the application's. Credit-life premium is the dummy's canned 199 cents. Nothing in these paths posted that premium. |
| `DebitOrderRailDummy.fixed_success` | Matched receipts at 00:00 Africa/Johannesburg. Sequence 1 was loan `000000000001`, 21 900 cents, 1 May 2026. |

`person-active` does not hold `lms.collection_campaign.write`. The campaign path used `EnigmaStub`, which returns a clear success for that role. No adapter was added.

## Fail closed

| Probe | Result |
|-------|--------|
| Book with every election null | `election-unset`: leniency_days is not set |
| Book with the in-duplum trigger and residual omitted | Agreement returned. Stored trigger `None`. Stored residual 5 000 cents |
| `Collections.bind` with trigger null | `trigger-unset`. No case stored |
| `resolve_residual_threshold_cents(None, None)` | 5 000 |
| April statement with no VAT rate | `vat-rate-unset` |

The 5 000 cent fill is C4 and C6. The successful book with a null trigger is C7.

## Normal lifecycle

R2 000 short-term, disbursed 1 April 2026, one instalment of 200 000 cents due 1 May 2026, 5% per month, actual/actual, initiation 0. No Laybye. Loan number `000000000001` for application `APP-00000001`.

April has 30 days. The section 9 fraction from 1 April to 1 May is 30/30, so the opening service fee is the full R60 plus VAT.

| Item | Cents |
|------|------:|
| April interest, 30 daily memos, billed at month-end | 10 000 |
| April service fee (6 000 ex VAT + 900 VAT) | 6 900 |
| April principal | 200 000 |
| 1 May receipt | 21 900 |
| Section 126: interest, then service, then principal | 10 000 + 6 900 + 5 000 |
| Principal after the receipt | 195 000 |
| Interest and service after the receipt | 0 |

The 1 May statement opening equals the April closing, including the zero buckets. Source: `previous-closing`. The 1 May closing principal is 195 000. The day's interest memo is 3.1451612903 rands and was not billed. That memo is 5% of R1 950 divided by 31. A memo on the R2 000 balance at the start of 1 May would be 3.2258064516 rands. See S3.

No statement-ready push was sent. See N6.

## Open-period variation

Disbursed 15 April 2026. Instalments 100 000 cents on 1 May 2026 and 100 000 cents on 1 June 2026, so May's month-end is still inside the term. The first due date is in a later month. Inclusive days from 15 April through 30 April are 16. April has 30 days.

| Fee | Levied | Ex VAT | VAT | Total |
|-----|--------|-------:|----:|------:|
| Opening month | 30 April 2026 | 3 200 | 480 | 3 680 |
| Next month | 31 May 2026 | 6 000 | 900 | 6 900 |

April interest billed 5 333 cents (16 days on R2 000 at 5%). May closing interest is 15 333 cents and closing service is 10 580 cents, which is 3 680 + 6 900. The next month is the full fee.

## Weekly payment

R2 000, disbursed 1 April 2026, weekly instalments of 40 000 cents on 8, 15, 22 and 29 April and 6 May 2026. `PaymentRail.capitalise_due_amounts` ran on each due date. The interest bucket was 0 before the first of those calls.

| Item | Result |
|------|--------|
| Accrual days | 36, from 1 April through 6 May |
| Interest bills (value date, cents) | 8 April 2 667; 15 April 2 333; 22 April 2 333; 29 April 2 334; 6 May 2 268 |
| Bill total | 11 935 |
| April service fee | 1 400 ex VAT + 210 VAT = 1 610, levied 1 April. Fraction 7/30 |
| May service fee | 6 000 ex VAT + 900 VAT = 6 900, levied 6 May. One fee, not one per week |

11 935 cents is April's R100 plus six May days (1 935 cents). Interest was capitalised on each weekly due date. The service fee stayed monthly.

## Settlement in term

R2 000 disbursed 1 April 2026, final instalment 1 June 2026. Quote as of 15 May 2026, delivered the same day, no extra holidays. The quote did not change ledger balances. `valid_until` is 22 May 2026.

| Component | Cents |
|-----------|------:|
| Principal | 200 000 |
| Interest | 14 839 |
| Service | 13 800 |
| Initiation | 30 475 |
| Early termination | 0 |
| Total | 259 114 |

14 839 cents is April's 10 000 plus 1–15 May (4 839). Service of 13 800 cents is two full months: the April fraction from 1 April to 1 June is above one and is capped, and the May settlement month is the full fee, not 15/31. Early termination is 0.

The initiation component is not the booked fee. See S2. Ledger has no `quote_settlement`. See S1.

## Collections default and in-duplum

Same R2 000 loan as the normal path. Leniency 3 calendar days. Trigger `collections_default`. Residual threshold set explicitly to 10 000 cents. No receipt before the flag date. April statement billed 10 000 interest and 6 900 service.

| Observe | Collections default | Ceiling | Episodes |
|---------|---------------------|--------:|---------:|
| 1 May 2026 | false | none | 0 |
| 4 May 2026 | true | 200 000 | 1 |
| 5 May 2026, after 20 000 cents | true | 200 000 | 1 |

The ceiling equals the unpaid principal at the flag (200 000). A contractual breach was also recorded for 1 May. The 20 000 cent receipt on 5 May, recognised at 00:00, was allocated interest 10 000, service 6 900, principal 3 100. Principal became 196 900. Interest and service became 0. Outstanding went from 216 900 to 196 900. The episode stayed open and the ceiling stayed 200 000.

## Write-off

R100 (10 000 cents), same dates and rate, residual threshold 10 000 cents, no open episode. The exact 10 000 cent instalment on 1 May was allocated to the April interest and the service fee first. Before any staff instruction the loan was still `active` with principal 7 400 and every other bucket 0.

`Collections.propose_residual_write_off` on 2 May 2026 posted the 7 400 cents. Every bucket is 0. `written_off` is true.

## Collection campaign

R2 000 disbursed 1 April 2026, contractual end 1 June 2026, stored rate 0.05. Notice 24 April 2026. `earliest_effective` returned 4 May 2026. Campaign end 10 May 2026. Rate reduction 0.02, scope `campaign_period`. No fee reduction and no payment holiday.

| Day | Rate | Memo (rands) | Base (cents) |
|-----|------|-------------:|-------------:|
| 4 May 2026 | 0.03 | 1.9354838710 | 200 000 |
| 11 May 2026 | 0.05 | 3.2258064516 | 200 000 |

The schedule, the contractual end (1 June 2026), and the stored rate (0.05) were unchanged.

## Migration prefix

The merged tree had both `0008_collection_campaigns.sql` and `0008_layer2_staff.sql`. The staff file was renamed to `0009_layer2_staff.sql`. The SQL body was not changed. Prefixes `0001` through `0009` are unique. `tests/test_layer1_gaps.py::test_migration_prefixes_apply_in_one_order` checks that.
