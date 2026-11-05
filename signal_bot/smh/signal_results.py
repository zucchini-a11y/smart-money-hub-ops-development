"""Private result-post captions and links for published signals."""
import re

from .domain import validate_analysis


OUTCOME_LABELS = {
    "profit": "Profit",
    "loss": "Loss",
    "breakeven": "Break-even",
    "not_stated": "Not stated",
}


def telegram_message_link(chat_id, message_id):
    """Return a link only when the configured destination is a private supergroup/channel."""
    if not message_id:
        return None
    chat = str(chat_id)
    if not re.fullmatch(r"-100\d{6,}", chat):
        return None
    return f"https://t.me/c/{chat[4:]}/{int(message_id)}"


def default_result_caption(direction, outcome):
    if direction not in ("BUY", "SELL") or outcome not in OUTCOME_LABELS:
        raise ValueError("Choose a saved signal direction and administrator-confirmed result.")
    emoji = "🟢" if direction == "BUY" else "🔴"
    return (
        "📊 VAYDA SMART MONEY HUB — TRADE UPDATE\n"
        f"{emoji} Direction: {direction}\n"
        f"📈 Result: {OUTCOME_LABELS[outcome]}\n\n"
        "NO CONFIRMATION, NO ENTRY.\n"
        "— VAYDA SMART MONEY HUB"
    )


def validate_result_caption(text, direction, outcome):
    if direction not in ("BUY", "SELL") or outcome not in OUTCOME_LABELS:
        raise ValueError("Choose a saved signal direction and administrator-confirmed result.")
    text = validate_analysis(text)
    result_label = re.escape(OUTCOME_LABELS[outcome])
    if not re.search(rf"(?im)^\s*(?:📈\s*)?Result:\s*{result_label}\s*$", text):
        raise ValueError(f"Keep the confirmed “Result: {OUTCOME_LABELS[outcome]}” line in the caption.")
    if not re.search(rf"(?im)^\s*(?:[🟢🔴]\s*)?Direction:\s*{direction}\s*$", text):
        raise ValueError(f"Keep the saved “Direction: {direction}” line in the caption.")
    return text
