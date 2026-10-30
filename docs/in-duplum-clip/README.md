# In-duplum clip

Decision 7 is the rule. This note says how the Day-1 clip is posted. It does not name the three unsigned section 103(5) edges, and it does not change the ceiling.

The ceiling stays unpaid principal at the first default in the episode, including initiation capitalised before that default. `duplum_base_cents` still assembles that amount. Amounts are integer cents.

## When the clip acts

The clip is on for Day-1.

While an episode is open, interest, fees (initiation, service, and additional monthly), credit insurance, default administration, and collection costs accrue toward that episode's ceiling. Charges that are levied before the episode opens do not count.

When the accrued cents equal the ceiling:

- The loan is flagged `in_duplum_ceiling_reached`.
- One operational audit row, `IN_DUPLUM_CEILING`, records the warning. The payload carries `warning`, `loan_id`, `episode_no`, `ceiling_cents`, and `accrued_cents`.
- Further levies of those charges post nothing until the episode is closed. A levy that would pass the ceiling is posted only up to the remaining cents, so the accrued total equals the ceiling. The unbilled interest above that total is not left for a later bill.

A payment allocates to the balance. It does not reduce `accrued_cents` and it does not clear the flag, so charges do not restart.

A cure closes the episode and clears the flag when the in-duplum trigger is collections default. A contractual-breach episode stays open, and the flag stays set. The next collections default opens a new episode. Its ceiling is the unpaid principal at that later default.

The recognition instant is 00:00 Africa/Johannesburg. `value_date` is the Johannesburg calendar day of that instant. The warning uses the same recognition instant as the levy that reached the ceiling.

This follows Nedbank v NCR [2011] ZASCA 35 and NCR guidance. It will be adjusted if counsel names a different reading.

## What an operator sees

- `Ledger.in_duplum_clip_status` returns the flag, the warning, the open episode number, and the ceiling and accrued cents.
- `Collections.view` returns `in_duplum_ceiling_reached` and `in_duplum_ceiling_warning`.
- The audit extract for the organisation includes the `IN_DUPLUM_CEILING` warning.
- The daily batch stores `accounts_at_ceiling` on the run. The status query returns it. The finish audit detail includes `accounts_at_ceiling=<count>`. An account that has reached the ceiling is still a processed account. It is not counted as a failure. The calculation reports the hit with `account_hit_in_duplum_ceiling`. A calculation that does not track the ceiling reports false, and the count stays 0.
