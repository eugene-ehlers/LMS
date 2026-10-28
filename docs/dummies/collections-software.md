# Collections-software dummy

The LMS tells the collections software that an account is in collections default. The dummy returns a fixed acknowledgement, or nothing. It does not generate a collection notice, and the port has no notice operation. The LMS does not send collection notices.

Contact details are not on this contract. The collections software obtains them from the client database via the application number, which is linked to the loan number and the ID number.

Call site: `collections.flag_collections_default(flag)`.

| Scenario | Constructor | Result |
| --- | --- | --- |
| Acknowledge | `CollectionsSoftwareDummy.acknowledging()` | Acknowledgement |
| Nothing | `CollectionsSoftwareDummy.silent()` | `None` |

## Request

`CollectionsDefaultFlag`

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `loan_number` | string | yes | The account |
| `application_number` | string | yes | Link to the client database |
| `id_number` | string | no | The other link already named for that lookup |

Example:

```text
loan_number: LN-1001
application_number: APP-00000001
id_number: 0000000000000
```

There is no notice text, template, or delivery address.

## Response

`CollectionsAcknowledgement`, or nothing.

| Field | Type | Notes |
| --- | --- | --- |
| `loan_number` | string | Echo of the flag |
| `application_number` | string | Echo of the flag |
| `acknowledged` | `true` | Present only when an acknowledgement is returned |

```text
loan_number: LN-1001
application_number: APP-00000001
acknowledged: true
```

Silent mode returns nothing after the same request validation. A blank loan number or application number is a contract error in both modes.
