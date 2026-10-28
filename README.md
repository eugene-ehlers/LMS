# LMS

Post-origination loan management for South African white-label credit providers. Identity, organisations, memberships, mandates, and product enrolment come from Enigma.

`docs/LOCKED_DECISIONS.md` is the source of truth. The Enigma port design is [docs/enigma/lms-enigma-interface.md](docs/enigma/lms-enigma-interface.md). The implementation note is [docs/enigma/IMPLEMENTATION_NOTE.md](docs/enigma/IMPLEMENTATION_NOTE.md).

`src/lms/enigma/` is the LMS-side port. HTTP paths stay unbound and raise `UnboundEnigmaPort`. `python3 -m pytest tests/test_enigma_session.py` runs the session, freeze, and machine checks.
