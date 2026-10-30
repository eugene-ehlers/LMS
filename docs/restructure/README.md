# Restructure

A restructure changes the contractual term or the contractual instalment. It is a new credit agreement linked to the original. It is not a collection campaign, an early settlement, or a settlement re-advance.

The decision engine supplies the new rate, the new term, and the new instalment. The LMS stores those values. It does not re-decide concurrent, subsequent, settled-and-readvanced, or restructure rules (Decision 13).

Client consent is required. The consent flag and the consent date are stored. A missing consent fails closed. A missing required election fails closed (Decision 19).

Amounts are integer cents. The recognition date is 00:00 Africa/Johannesburg (Decision 1).

| Topic | Document |
| --- | --- |
| Routes and status feedback | [routes.md](routes.md) |
| What is stored | [schema.md](schema.md) |
| Points the locks do not settle | [gaps.md](gaps.md) |

The orchestration flow is section 10 of `docs/ORCHESTRATION.md`. That section was missing. The steps recorded there are the restructure instruction and Decisions 13, 16, 19, and 23.
