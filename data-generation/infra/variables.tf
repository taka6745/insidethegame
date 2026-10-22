variable "subscription_id" {
  type = string
}

variable "location" {
  type    = string
  default = "australiaeast"
}

variable "name_prefix" {
  type    = string
  default = "itg-feed-dev"
}

variable "etl_state_path" {
  type        = string
  default     = "../../etl/infra/terraform.tfstate"
  description = "The ETL's state, read for the shared environment and registry and the send-only Event Hubs key."
}

variable "image_tag" {
  type        = string
  default     = null
  description = "feed image tag in the shared registry; the Container App is created once this is set."
}

variable "min_replicas" {
  type        = number
  default     = 1
  description = "1 while matches may run (a run lives in the process); 0 between demos."
}

variable "demo_seeds" {
  type        = bool
  default     = false
  description = "Demo seed export/restore routes (DEMO_SEEDS=1; PLAN.md §10.6). On for the judge build (`./dev azure up`), off for a production release."
}
