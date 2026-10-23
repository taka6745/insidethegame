# Development

> **In short:** every check runs without Azure: formatting, validation and mock-provider tests in Docker, and unit tests for `./dev azure`.

| | |
| --- | --- |
| **Checks** | `./dev terraform check` (all five stacks), `python3 -m unittest` in `terraform/azure` |
| **CI** | Both, in `.github/workflows/ci.yml` |

```sh
./dev terraform check                                    # fmt -check, init -backend=false, validate, terraform test
cd terraform/azure && python3 -m unittest test_azure -v  # ./dev azure with a faked toolbox
```

- `tests/design.tftest.hcl` checks the app stack's resource graph with a mock `azurerm` provider and stubbed remote state.
- `guard/tests/guard.tftest.hcl` checks the budgets and the last resort.
- `./dev terraform check` copies each infra folder without local `.terraform` state or tfvars; init downloads providers only.
