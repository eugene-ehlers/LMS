"""Process entry for the test deployment.

Staff screens stay on their existing routes. This module adds the health
check, the consumer pages, and the stub exercise. It does not price a loan.
"""

from __future__ import annotations

import os

from lms.exercise import Exercise, ExerciseError
from lms.objects import S3Store
from lms.servicing.errors import ServicingError
from lms.staff_ui.app import Session, build_app, make_server
from lms.staff_ui import render
from lms.stubs.debit_file import DebitStubError
from lms.stubs.decision_quote import QuoteStubError
from lms_config.exceptions import CalculationInputError


def serve_lms(host: str, port: int) -> None:
    store = None
    if os.environ.get("LMS_REQUIRE_DEPLOY_CONFIG") == "1":
        from lms.migrate import reference_data_present, require_deploy_config

        require_deploy_config()
        reference_data_present()
        store = S3Store(os.environ["LMS_S3_BUCKET"])
        store.check()
    exercise = Exercise(objects=store)
    app = build_app()
    server = make_server(app, host, port, front=build_front(exercise))
    print(f"Staff screens at http://{host}:{port}/staff/", flush=True)
    print(f"Exercise at http://{host}:{port}/exercise", flush=True)
    print(f"Consumer registration at http://{host}:{port}/self/register", flush=True)
    server.serve_forever()


def build_front(exercise: Exercise):
    def front(method: str, path: str, form: dict, session: Session):
        return route(exercise, session, method, path, form)

    return front


def route(exercise: Exercise, session: Session, method: str, path: str, form: dict):
    parts = [part for part in path.split("/") if part]
    if parts == ["exercise"] and method == "GET":
        return _html(200, "Book and pay", _exercise_page(exercise))
    if parts == ["exercise", "book"] and method == "POST":
        return _action(exercise.book, form, "Booked")
    if parts == ["exercise", "pay"] and method == "POST":
        return _action(exercise.pay, form, "Debit-order stub")
    if parts == ["exercise", "statement"] and method == "POST":
        return _action(exercise.issue_statement, form, "Statement stored")
    if parts == ["exercise", "brand"] and method == "POST":
        return _action(exercise.store_brand, form, "Brand asset stored")
    if parts == ["self"] and method == "GET":
        return _html(200, "Consumer", _self_index())
    if parts == ["self", "register"]:
        return _enigma_page(method, "register")
    if parts == ["self", "sign-on"]:
        return _enigma_page(method, "sign-on")
    if parts == ["self", "statement"] and method == "GET":
        return _stored_statement(exercise, session)
    if parts == ["self", "settlement-quote"] and method == "GET":
        return _stored_quote(session)
    return None


def _action(fn, form: dict, title: str):
    try:
        result = fn(form)
    except ExerciseError as exc:
        return _html(422, title, _failure(exc.code, str(exc)))
    except (ServicingError, QuoteStubError, DebitStubError) as exc:
        code = getattr(exc, "code", "refused")
        return _html(422, title, _failure(code, str(exc)))
    except CalculationInputError as exc:
        return _html(422, title, _failure("election-unset", str(exc)))
    except Exception as exc:
        return _html(422, title, _failure("refused", str(exc)))
    lines = "".join(f"<li>{render.esc(key)}: {render.esc(value)}</li>" for key, value in result.items())
    inner = f"<h1>{render.esc(title)}</h1><ul>{lines}</ul><p><a href=\"/exercise\">Back</a></p>"
    return _html(200, title, inner)


def _enigma_page(method: str, kind: str):
    title = "Registration" if kind == "register" else "Sign on"
    if method == "POST":
        return _html(
            422,
            title,
            _failure(
                "enigma-redirect",
                "Registration and sign-on are Enigma. This screen does not accept those details.",
            ),
        )
    if method != "GET":
        return None
    message = (
        "Registration and sign-on are Enigma. No Enigma page address is configured, "
        "so this screen does not send the browser to another site and it does not collect "
        "an email address or a password. Staff on the test deployment use the session form at /staff/."
    )
    inner = (
        f"<h1>{render.esc(title)}</h1><p>{render.esc(message)}</p>"
        f"<form method=\"post\" action=\"/self/{kind}\"><button type=\"submit\">Continue</button></form>"
    )
    return _html(200, title, inner)


def _stored_statement(exercise: Exercise, session: Session):
    refused = _consumer_gate(session)
    if refused is not None:
        return refused
    rows = [
        statement
        for statement in exercise.servicing.statements.values()
        if statement.organisation_id == session.organisation_id and statement.person_id == session.person_id
    ]
    if not rows:
        body = "<p>No stored statement is held for this consumer.</p>"
    else:
        items = "".join(
            "<li>"
            f"{render.esc(statement.statement_id)} "
            f"{render.esc(statement.period_start.isoformat())} to {render.esc(statement.period_end.isoformat())}"
            "</li>"
            for statement in rows
        )
        body = f"<ul>{items}</ul>"
    return _html(200, "Stored statement", f"<h1>Stored statement</h1>{body}")


def _stored_quote(session: Session):
    refused = _consumer_gate(session)
    if refused is not None:
        return refused
    return _html(
        200,
        "Settlement quote",
        "<h1>Settlement quote</h1><p>No stored settlement quote is held for this consumer.</p>",
    )


def _consumer_gate(session: Session):
    if session.enigma_status == "timeout":
        return _html(
            503,
            "Enigma",
            _failure(
                "enigma-timeout",
                "LOCKED_DECISIONS §15: Enigma timed out. The statement and the quote stay unopened.",
            ),
        )
    if session.enigma_status == "suspended":
        return _html(
            403,
            "Enigma",
            _failure(
                "enigma-suspended",
                "LOCKED_DECISIONS §15: the enrolment is suspended. The statement and the quote stay unopened.",
            ),
        )
    if session.enigma_status != "active" or not session.person_id.strip() or not session.organisation_id.strip():
        return _html(
            403,
            "Enigma",
            _failure(
                "enigma-sign-on",
                "A consumer sees a stored statement or settlement quote only after Enigma sign-on. This screen does not issue either.",
            ),
        )
    return None


def _exercise_page(exercise: Exercise) -> str:
    rows = exercise.agreements()
    if rows:
        body = "".join(
            "<tr>"
            f"<td>{render.esc(row['loan_number'])}</td>"
            f"<td>{render.esc(row['application_number'])}</td>"
            f"<td>{render.esc(row['agreement_id'])}</td>"
            f"<td>{render.esc(row['status'])}</td>"
            f"<td>{render.esc(row['organisation_id'])}</td>"
            f"<td>{render.esc(row['person_id'])}</td>"
            "</tr>"
            for row in rows
        )
        table = (
            "<table><thead><tr><th>Loan number</th><th>Application</th><th>Agreement</th>"
            f"<th>Status</th><th>Organisation</th><th>Person</th></tr></thead><tbody>{body}</tbody></table>"
        )
    else:
        table = "<p>No agreement is held in this process.</p>"
    return f"""
<h1>Book and pay</h1>
<p>The decision-engine quote stub and the debit-order file stub call the existing servicing methods. A blank election is refused. Nothing on this page chooses a rate.</p>
<p>Use a synthetic identity and a test NCR number. An example identity is person-test-001, Test Consumer, id 0000000000000, 1 Dummy Street, Johannesburg. An example NCR number for a later compliance save is NCRCP999999. Those values are not filled in for you.</p>
{table}
<h2>Book</h2>
<form method="post" action="/exercise/book">
<label>Organisation id <input name="organisation_id" autocomplete="off"></label>
<label>Person id <input name="person_id" autocomplete="off"></label>
<label>Full name <input name="full_name" autocomplete="off"></label>
<label>Identity number <input name="id_number" autocomplete="off"></label>
<label>Service address <input name="service_address" autocomplete="off"></label>
<label>Idempotency key <input name="idempotency_key" autocomplete="off"></label>
<label>Product
<select name="product_code">
<option value=""></option>
<option value="micro_short_term">micro_short_term</option>
<option value="unsecured_personal">unsecured_personal</option>
</select>
</label>
<label>Frequency <input name="frequency" autocomplete="off"></label>
<label>Cash advanced, cents <input name="cash_advanced_cents" inputmode="numeric" autocomplete="off"></label>
<label>Schedule due date <input name="due_on" autocomplete="off"></label>
<label>Schedule amount, cents <input name="schedule_amount_cents" inputmode="numeric" autocomplete="off"></label>
<label>Recognised at <input name="recognised_at" autocomplete="off"></label>
<label>Disbursed at <input name="disbursed_at" autocomplete="off"></label>
<label>Leniency days <input name="leniency_days" inputmode="numeric" autocomplete="off"></label>
<label>Full payment threshold percent <input name="full_payment_threshold_percent" autocomplete="off"></label>
<label>Interest on deferred initiation <input name="interest_on_deferred_initiation" autocomplete="off"></label>
<label>Repo-rate fall <input name="repo_rate_fall" autocomplete="off"></label>
<label>Day count <input name="day_count_code" autocomplete="off"></label>
<label>VAT on rand maxima <input name="vat_on_rand_maxima" autocomplete="off"></label>
<label>Late disbursement <input name="late_disbursement" autocomplete="off"></label>
<label>Partial prepayment <input name="partial_prepayment" autocomplete="off"></label>
<label>In-duplum trigger <input name="in_duplum_trigger" autocomplete="off"></label>
<label>Residual threshold, cents <input name="residual_write_off_threshold_cents" autocomplete="off"><span class="note">Blank stays unset.</span></label>
<button type="submit">Book with the quote stub</button>
</form>
<h2>Debit-order receipt</h2>
<form method="post" action="/exercise/pay">
<label>Agreement id <input name="agreement_id" autocomplete="off"></label>
<label>Amount, cents <input name="amount_cents" inputmode="numeric" autocomplete="off"></label>
<label>Due date <input name="due_on" autocomplete="off"></label>
<label>Recognition date <input name="recognition_date" autocomplete="off"></label>
<label>Stub outcome
<select name="outcome">
<option value=""></option>
<option value="success">success</option>
<option value="failure">failure</option>
</select>
</label>
<button type="submit">Apply the debit-order stub</button>
</form>
<h2>Statement artifact</h2>
<form method="post" action="/exercise/statement">
<label>Organisation id <input name="organisation_id" autocomplete="off"></label>
<label>Person id <input name="person_id" autocomplete="off"></label>
<label>Period start <input name="period_start" autocomplete="off"></label>
<label>Period end <input name="period_end" autocomplete="off"></label>
<label>Interest cap present
<select name="interest_cap_present">
<option value=""></option>
<option value="true">true</option>
<option value="false">false</option>
</select>
</label>
<label>VAT rate <input name="vat_rate" autocomplete="off"><span class="note">Blank leaves the rate unset.</span></label>
<button type="submit">Issue and store</button>
</form>
<h2>Brand asset</h2>
<form method="post" action="/exercise/brand">
<label>Organisation id <input name="organisation_id" autocomplete="off"></label>
<label>Asset name <input name="asset_name" autocomplete="off"></label>
<label>Body <textarea name="body"></textarea></label>
<button type="submit">Store in the bucket</button>
</form>
"""


def _self_index() -> str:
    return """
<h1>Consumer</h1>
<ul>
<li><a href="/self/register">Registration</a></li>
<li><a href="/self/sign-on">Sign on</a></li>
<li><a href="/self/statement">Stored statement</a></li>
<li><a href="/self/settlement-quote">Settlement quote</a></li>
</ul>
<p>Registration and sign-on are Enigma. The test deployment has no Enigma address, so those pages do not redirect.</p>
"""


def _failure(code: str, message: str) -> str:
    return (
        "<h1>This step did not succeed</h1>"
        f"<p>Code: {render.esc(code)}</p>"
        f"<p>{render.esc(message)}</p>"
        "<p><a href=\"/exercise\">Back</a></p>"
    )


def _html(status: int, title: str, inner: str):
    session = Session()
    body = render.document(title, session, inner, show_nav=True).encode("utf-8")
    return status, "text/html; charset=utf-8", body
