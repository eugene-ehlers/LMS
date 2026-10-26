# LMS

Post-origination loan management for a white-label South African book. Identity, organisations, memberships, and mandates stay in Enigma. This repository currently locks the day-1 calculation rules.

The rules, the worked examples, and the open National Credit Act choices are in [docs/day1-calculation-rules.md](docs/day1-calculation-rules.md). The pure functions live in `src/lms/calc/`. The figures in the rules document are pinned by `tests/test_day1_examples.py`.

```bash
python3 -m pip install pytest
PYTHONPATH=src python3 -m pytest
```
