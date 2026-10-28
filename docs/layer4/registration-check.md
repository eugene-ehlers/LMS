# Registration check before the statement-ready push

A consumer who wants to see the statement must register via Enigma and sign in (locked decisions 15 and 27). The LMS does not store the consumer's contact number or email for this purpose. LMS registration and sign-on pages direct the consumer to Enigma. They do not implement registration or sign-on.

The push is sent only after Enigma confirms that the consumer is registered. The push itself does not require the consumer to be signed in at that moment. Seeing the statement does.

## What is called

`consumer_registration(person_id, request_id) -> RegistrationView`

`RegistrationView` has three fields: `person_id`, `status`, and `enigma_request_id`. It has no email, mobile, or NCR number.

The development stand-in is `DummyEnigma` in `src/lms/notifications/enigma_dummy.py`. A later real Enigma client is called the same way when it exposes `consumer_registration`. Until then, an object that only offers `read_live_identity` fails closed with `enigma-unbound`. That read returns email and mobile (Enigma port on `origin/cursor/enigma-interface-d0c7` at `0cabd41`). This layer does not call it and does not copy those fields.

The port on that branch has no registration operation. The dummy is the stand-in the task allows. It is not an identity store. Unknown people are unregistered. The answers it can give are the ones below.

| Enigma answer | Code | Push |
| --- | --- | --- |
| `registered`, and the person id matches |  | Sent, once the statement and the NCR checks have passed |
| `unregistered`, including a person the dummy does not know | `consumer-unregistered` | Not sent |
| `suspended` | `enigma-suspended` | Not sent |
| `ambiguous`, an unknown status, or an answer for a different person | `enigma-ambiguous` | Not sent |
| Timeout | `enigma-timeout` | Not sent |
| The operation is missing | `enigma-unbound` | Not sent |

Timeout, an ambiguous status, and a clear suspended enrolment fail closed (locked decision 15). Nothing is sent in those cases.

The NCR registration number is not part of this check. Enigma does not hold it (locked decisions 15 and 21). A blank number on the issued statement fails closed in `src/lms/notifications/ncr.py` before the push is delivered.

## Registration and sign-on pages

`registration_page` and `sign_on_page` return a 302 to the configured Enigma address. The body tells the consumer to continue at Enigma. It does not contain a form, and it does not accept a contact number, an email address, or a password.

The locked file does not give those addresses. When either address is unset, the page fails closed with `enigma-url-unset`. No address is invented.

## Seeing the statement

`view_as_consumer` takes the person id from a clear active Enigma session, then runs the same registration check. The issued statement is returned as Layer 1 stored it. It is not rebuilt. A missing session is `reauthenticate`. A session for a different person does not open this client's statement. An unregistered consumer is refused even if a statement exists.

## Call centre

Staff with the appropriate role can read the issued statement and give the information to a consumer who phones (locked decision 27). `view_as_staff` asks Enigma `allow_staff_statement` for the credit-provider organisation. The dummy allows the read only when the session Enigma returned includes `lms.account.statement.read`. That action id is the name already on the Enigma port catalogue. Locked decision 27 does not name the role. No local staff list grants the read.

A timeout, an ambiguous session, a suspended enrolment, a missing allow, or a session for another organisation fails closed. The consumer does not have to be registered for this staff read. The method does not create a collection notice.

## Actor on the push

The push audit needs the person Enigma says is signed in (locked decision 23). `confirm_actor` is that session check. A missing, expired, revoked, suspended, timed-out, or unclear session fails closed, and no system user is substituted.

The locked file does not name a machine action for this job. The Enigma catalogue's machine action is `lms.allocation.run`. This layer does not reuse it and does not add a notification action to the locked file.
