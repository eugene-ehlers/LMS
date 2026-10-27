# LMS

Post-origination loan management for South African white-label credit providers. Identity, organisations, memberships, mandates, and product enrolment come from Enigma.

The consumer port is specified in [docs/enigma/lms-enigma-interface.md](docs/enigma/lms-enigma-interface.md). Decisions on staff boarding, machine identity, fail-closed servicing, the NCR number, rand ceilings, and the booking identity freeze are locked there.

LMS-side sketches live in `src/lms/enigma/` (`EnigmaClient`, session middleware, identity freeze, ceilings, machine exchange). HTTP paths stay unbound until `eugene-ehlers/enigma` can be read. `python3 -m pytest tests/test_enigma_session.py` checks the session and freeze behaviour.
