"""Visible assistant text shared by runtime history and evaluation conversations."""


def assistant_message(response: dict) -> str:
    if response.get("status") == "ready" and response.get("goal"):
        return response["goal"]["description"]
    clarification = response.get("clarification") or {}
    text = clarification.get("question") or response.get("message") or "Please clarify your request."
    if clarification.get("options"):
        text += "\nOptions:\n" + "\n".join(
            f"{index}. {option}" for index, option in enumerate(clarification["options"], 1))
    return text
