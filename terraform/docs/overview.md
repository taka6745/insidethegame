# Overview

> **In short:** one command deploys every service to Azure from an empty subscription; the demo build serves the public demo URL.

| | |
| --- | --- |
| **Status** | Deployed (demo build, redeployed 23 Oct 2026 with the fictional league; every agent on `gpt-6.1-sol`; seeds 20′, HT, 60′, 85′ recorded on Azure) · `./dev terraform check` and `azure/test_azure.py` in CI |
| **Region** | Australia East |
| **Public** | Only the frontend (behind the Cloudflare edge proxy) |

## 1. Stacks

*In short: five Terraform roots, applied in order.*

| Order | Stack | Resource group |
| --- | --- | --- |
| 0 | [`terraform/guard`](../guard/) | `rg-itg-guard` (kept by `down`) |
| 1 | [`etl/infra`](../../etl/infra/) | `rg-itg-etl-dev` |
| 2 | [`narrative-engine/infra`](../../narrative-engine/infra/) | `rg-itg-narrative-dev` |
| 3 | [`data-generation/infra`](../../data-generation/infra/) | `rg-itg-feed-dev` |
| 4 | [`terraform/`](../) | `itgdemo-rg` |

## 2. Planned, not built

*In short: production hardening ([decisions §2](decisions.md#2-before-a-production-release)).*

VNet, managed identities, remote state, auth on demo control, multiple backend replicas.
