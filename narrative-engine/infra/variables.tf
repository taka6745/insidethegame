variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "name_prefix" {
  type    = string
  default = "itg-narrative-dev"
}

variable "etl_state_path" {
  type        = string
  default     = "../../etl/infra/terraform.tfstate"
  description = "The ETL's local state, read (only) for its Service Bus namespace."
}

variable "budget_amount" {
  type        = number
  default     = 20
  description = "Monthly budget for the resource group, in the subscription's billing currency."
}

variable "budget_emails" {
  type        = list(string)
  description = "Who gets budget alerts. Set in local.auto.tfvars (git-ignored)."
}

variable "budget_start" {
  type        = string
  default     = "2026-10-01T00:00:00Z"
  description = "First day of a month; budgets cannot start in the past when created."
}

variable "models" {
  type = map(object({
    version  = string
    capacity = number # thousands of tokens per minute
    format   = optional(string, "OpenAI")
    sku      = optional(string, "GlobalStandard")
    model    = optional(string) # the model's name when it differs from the deployment name (the key)
  }))
  default = {
    # Every writing role (summary, compression, analyst, author, follow authoring). The deployment name stays
    # generic, so a different model is a change here only. GlobalStandard quota in Australia East: 250K TPM, shared
    # with the backend's `questions` (130K: cross-match questions carry every live match; 50K hit 429).
    "writer" = { model = "gpt-6.1-sol", version = "2026-09-29", capacity = 120 }
    # Alternatives any engine or backend role can switch to live under /dev/config/models; the
    # backend reaches them on this account too. Quota in Australia East: luna 250K, mini 1000K TPM.
    "gpt-6-luna" = { version = "2026-09-22", capacity = 100 }
    "gpt-5-mini" = { version = "2025-08-07", capacity = 100 }
    # Story-follow triggers and the authors' claim checks (narrative_engine/decisions, SystemOne API). Capacity is
    # requests per minute (DataZoneStandard quota in Australia East: 60).
    "decision-1" = { model = "Microsoft-Decision-1", version = "1", capacity = 50, format = "Microsoft", sku = "DataZoneStandard" }
  }
  description = "Foundry deployments, by deployment name."
}

variable "decision" {
  type = object({
    deployment    = string # a key of var.models
    max_questions = number # questions per SystemOne request; larger batches are split
  })
  default     = { deployment = "decision-1", max_questions = 128 }
  description = "The engine's decision model (Microsoft-Decision-1): story-follow triggers and claim checks."

  validation {
    condition     = var.decision.max_questions >= 1
    error_message = "decision.max_questions must be at least 1."
  }
}

variable "agents" {
  type = map(object({
    model  = string
    effort = optional(string) # reasoning_effort; omit for models without reasoning
  }))
  default = {
    summary     = { model = "writer", effort = "low" } # gpt-6.1-sol: low is its lowest effort
    compression = { model = "writer", effort = "low" }
    analyst     = { model = "writer", effort = "low" }
    author      = { model = "writer", effort = "low" }
  }
  description = "Model (a key of var.models) and reasoning effort for each agent."

  validation {
    condition     = toset(keys(var.agents)) == toset(["summary", "compression", "analyst", "author"])
    error_message = "Set exactly the agents summary, compression, analyst and author."
  }
}

variable "engine_image_tag" {
  type        = string
  default     = null
  description = "Image tag in the registry; the Container App is created once this is set."
}

variable "user_backend_url" {
  type        = string
  default     = null
  description = "User backend base URL: audience targets per matchId and prompts. Required once engine_image_tag is set (the engine has no fallback)."
}

variable "demo_seeds" {
  type        = bool
  default     = false
  description = "Demo seed export/restore routes (DEMO_SEEDS=1). On for the demo build (`./dev azure up`), off for a production release."
}
