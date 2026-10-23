# Devtools

> **In short:** `devtools/spadl_reference.py` regenerates `backend/contracts/spadl-reference.json`, the backend's copy of ETL's SPADL contract, so the runtime never reads another service's folder.

| | |
| --- | --- |
| **Code** | [`devtools/spadl_reference.py`](../../devtools/spadl_reference.py) → [`backend/contracts/spadl-reference.json`](../../backend/contracts/spadl-reference.json) |
| **Run** | `cd user-backend && python -m devtools.spadl_reference` after an ETL contract change |
| **Tests** | `test_spadl_contract.py` fails while the generated file is stale |
| **Status** | Implemented, tested; developer-only (not in the runtime image) |

## 1. What it generates

*In short: enums and meanings from ETL's schema, Opta sources probed from its converter.*

Enums, field meanings and zone rules come from `etl/contracts/spadl-action.schema.json`; the Opta source of each action type, result and body part is found by probing `etl/reference/spadl.py`'s rules (names from `etl/contracts/opta-codes.json`, else the converter's constants). Nothing is hand-copied. `models/actions.py` builds its enums from the file, and the [SPADL reference](adapters.md#5-spadl-reference) gives the agents its meanings.
