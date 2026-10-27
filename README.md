# LMS

Post-origination loan management for a white-label South African book. Identity, organisations, memberships, and mandates stay in Enigma. This repository currently locks the day-1 calculation rules.

[docs/LOCKED_DECISIONS.md](docs/LOCKED_DECISIONS.md) is the source of truth for decisions that have been locked. The formulas, worked examples, and points that file does not settle are in [docs/day1-calculation-rules.md](docs/day1-calculation-rules.md). The pure functions live in `src/lms/calc/`. The figures are pinned by `tests/test_day1_examples.py` and `tests/test_locked_alignments.py`.

```bash
python3 -m pip install pytest
PYTHONPATH=src python3 -m pytest
```
