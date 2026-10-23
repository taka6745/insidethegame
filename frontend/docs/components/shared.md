# shared/

> **In short:** helpers imported by `match/`, `lab/` and `dev/`. Shipped twice: inside the viewer's fingerprint (`/app/{hash}/shared/`) and at `/shared/` for the lab and console.

| | |
| --- | --- |
| **Status** | Implemented · unit-tested (`match-dom.test.ts`, `build.test.ts`) |
| **Code** | [`frontend/shared/`](../../shared/) |

| File | Exports |
| --- | --- |
| `dom.ts` | `node()` (element with text and class), `keyedList()` (reuse unchanged children by key) |
| `http.ts` | `parseResponse()` (JSON body; a failed response throws the backend's message with `status` and `code`), `ServiceError` |

The viewer keeps its own request wrappers (`match/api.ts`, `match/demo.ts`): they turn every failure into a plain sentence for viewers, while `parseResponse` shows developers the backend's message.
