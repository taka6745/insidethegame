variable "subscription_id" {
  description = "Real Azure subscription for a separately authorised cloud deployment. Mock tests supply a dummy ID."
  type        = string
}

variable "prefix" {
  description = "Lowercase prefix, 3-16 letters/digits, starting with a letter."
  type        = string
  default     = "itgdemo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.prefix))
    error_message = "Use 3-16 lowercase letters/digits, starting with a letter."
  }
}

variable "location" {
  type        = string
  default     = "australiaeast"
  description = "Check regional SKU availability before a cloud deployment."
}

variable "etl_state_path" {
  type    = string
  default = "../etl/infra/terraform.tfstate"
}

variable "narrative_state_path" {
  type    = string
  default = "../narrative-engine/infra/terraform.tfstate"
}

variable "feed_state_path" {
  type    = string
  default = "../data-generation/infra/terraform.tfstate"
}

variable "image_tag" {
  type        = string
  default     = null
  description = "user-backend and frontend image tag in the shared (ETL) registry; the apps are created once set."
}

variable "dev_admin" {
  type        = bool
  default     = true
  description = "Developer consoles behind basic auth (password: `terraform output -raw dev_admin_password`)."
}

variable "question_model" {
  type = object({
    name     = string # the deployment name: generic, so the model is swappable here
    model    = string
    version  = string
    capacity = number           # thousands of tokens per minute
    effort   = optional(string) # reasoning_effort for a reasoning model; omit for a plain chat model
  })
  default     = { name = "questions", model = "gpt-6.1-sol", version = "2026-09-29", capacity = 130, effort = "low" }
  description = "Azure OpenAI deployment (GlobalStandard) for the backend's question, replay and follow-planner agents."
}

variable "demo_seeds" {
  type        = bool
  default     = false
  description = "Demo seed export/restore routes (DEMO_SEEDS=1; PLAN.md §10.6). On for the judge build (`./dev azure up`), off for a production release."
}

variable "stream_start_url" {
  type        = string
  default     = null
  sensitive   = true
  description = "terraform/guard's stream-start webhook: demo control calls it on Start so Stream Analytics need not wait for the Event Hubs traffic alert."
}
