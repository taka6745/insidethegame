# Question, goal, replay and follow-planner agents use the engine's Azure AI Foundry account with their own
# Azure OpenAI deployment. With question_model.effort set (a reasoning model) they send reasoning_effort and
# no temperature (LOCAL_LLM_EFFORT, backend/adapters/llm.py chat_options).
resource "azurerm_cognitive_deployment" "questions" {
  name                 = var.question_model.name
  cognitive_account_id = local.narrative.foundry_account_id

  model {
    format  = "OpenAI"
    name    = var.question_model.model
    version = var.question_model.version
  }

  sku {
    name     = "GlobalStandard"
    capacity = var.question_model.capacity
  }
}
