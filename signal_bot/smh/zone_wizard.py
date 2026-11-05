"""Validated, resumable data model for the administrator's zone-creation wizard."""
from decimal import Decimal

from .domain import price, safe_text
from .zones import parse_zone

MARKET_CHOICES = ("Gold", "Forex", "Bitcoin", "Synthetic Indices", "Other")
TIMEFRAME_CHOICES = ("M5", "M15", "M30", "H1", "H4", "D1")
EXPIRY_CHOICES = (15, 30, 60, 240, 1440)
OTHER = "__other__"
SKIP = "__skip__"


def new_draft(*, independent=False, poi_direction=None, replaces_setup_id=None,
              approximate_zone=False):
    if poi_direction not in (None, "BUY", "SELL"):
        raise ValueError("POI direction must be BUY or SELL.")
    return {
        "kind": "zone",
        "wizard_version": 1,
        "step": "market",
        "history": [],
        "answers": {},
        "independent": bool(independent),
        "poi_direction": poi_direction,
        "replaces_setup_id": replaces_setup_id,
        "approximate_zone": bool(approximate_zone),
    }


def is_wizard(draft):
    return bool(
        draft
        and draft.get("kind") == "zone"
        and (draft.get("wizard_version") == 1 or draft.get("step") == "input")
    )


def normalize(draft):
    """Upgrade old zone drafts and remove their obsolete automatic-expiry step."""
    if draft and draft.get("kind") == "zone" and draft.get("step") == "input":
        return new_draft()
    if is_wizard(draft):
        answers = draft.get("answers", {})
        if draft.get("step") in ("expiry", "expiry_other") or "minutes" in answers:
            upgraded = dict(draft)
            upgraded_answers = dict(answers)
            upgraded_answers.pop("minutes", None)
            upgraded["answers"] = upgraded_answers
            if upgraded.get("step") in ("expiry", "expiry_other"):
                upgraded["step"] = "preview"
                upgraded["history"] = [
                    step for step in upgraded.get("history", []) if step != "expiry"
                ]
            return upgraded
    return draft


def _clean_text(value, field, limit):
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"Enter the {field}.")
    text = safe_text(raw, limit)
    if "|" in text or "\n" in text or "\r" in text:
        raise ValueError(f"Keep the {field} on one line and do not include |.")
    if field == "market name" and "/" in text:
        raise ValueError("Use a market name without /. Enter the symbol separately.")
    return text


def _expiry(value):
    text = str(value).strip()
    if not text.isdigit() or not 1 <= int(text) <= 1440:
        raise ValueError("Enter a whole number from 1 to 1440 minutes.")
    return int(text)


def _advance(draft, current, next_step):
    if draft.get("editing"):
        edit_field = draft.get("edit_field")
        if edit_field == "market" and next_step in ("other_market", "symbol"):
            draft["step"] = next_step
            return
        if edit_field == "timeframe" and next_step == "timeframe_other":
            draft["step"] = next_step
            return
        if edit_field == "expiry" and next_step == "expiry_other":
            draft["step"] = next_step
            return
        draft["step"] = "preview"
        draft.pop("editing", None)
        draft.pop("edit_field", None)
        return
    draft.setdefault("history", []).append(current)
    draft["step"] = next_step


def answer(draft, field, value):
    """Validate one answer and advance exactly one wizard step."""
    if not is_wizard(draft) or draft.get("step") != field:
        raise ValueError("That question is no longer current. Resume the saved draft.")
    answers = draft.setdefault("answers", {})
    next_step = None

    if field == "market":
        if value not in MARKET_CHOICES:
            raise ValueError("Choose a market using one of the buttons.")
        answers["market_kind"] = value
        answers.pop("other_market", None)
        answers.pop("symbol", None)
        if value == "Gold":
            answers["symbol"] = "XAUUSD"
            next_step = "low"
        elif value == "Other":
            next_step = "other_market"
        else:
            next_step = "symbol"

    elif field == "other_market":
        answers["other_market"] = _clean_text(value, "market name", 80)
        next_step = "symbol"

    elif field == "symbol":
        if value == SKIP:
            if answers.get("market_kind") != "Other":
                raise ValueError("Enter the symbol for this market.")
            answers["symbol"] = ""
        else:
            answers["symbol"] = _clean_text(value, "symbol", 40)
        next_step = "low"

    elif field == "low":
        low = price(str(value))
        high = answers.get("high")
        if high and Decimal(low) >= Decimal(high):
            raise ValueError("The lower zone price must be below the upper price.")
        answers["low"] = low
        next_step = "high"

    elif field == "high":
        high = price(str(value))
        low = answers.get("low")
        if not low or Decimal(high) <= Decimal(low):
            raise ValueError("The upper zone price must be greater than the lower price.")
        answers["high"] = high
        next_step = "timeframe"

    elif field == "timeframe":
        if value == OTHER:
            next_step = "timeframe_other"
        elif value == SKIP:
            answers["timeframe"] = ""
            next_step = "confirmation"
        elif value in TIMEFRAME_CHOICES:
            answers["timeframe"] = value
            next_step = "confirmation"
        else:
            raise ValueError("Choose a timeframe button, Other, or Skip.")

    elif field == "timeframe_other":
        answers["timeframe"] = "" if value == SKIP else _clean_text(value, "timeframe", 30)
        next_step = "confirmation"

    elif field == "confirmation":
        if value == SKIP:
            answers["confirmation"] = ""
        else:
            answers["confirmation"] = _clean_text(value, "confirmation", 300)
        next_step = "preview"

    elif field == "expiry":
        if value == OTHER:
            next_step = "expiry_other"
        else:
            answers["minutes"] = _expiry(value)
            next_step = "preview"

    elif field == "expiry_other":
        answers["minutes"] = _expiry(value)
        next_step = "preview"

    else:
        raise ValueError("This wizard question is not available.")

    _advance(draft, field, next_step)
    return draft


def begin_edit(draft):
    if not is_wizard(draft) or draft.get("step") != "preview":
        raise ValueError("Open the setup preview before editing.")
    draft["step"] = "edit"
    draft.pop("editing", None)
    draft.pop("edit_field", None)
    return draft


def editable_fields(draft):
    answers = draft.get("answers", {})
    fields = ["market"]
    if answers.get("market_kind") != "Gold":
        fields.append("symbol")
    fields.extend(("low", "high", "timeframe", "confirmation"))
    return fields


def choose_edit(draft, field):
    if not is_wizard(draft) or draft.get("step") != "edit":
        raise ValueError("Open Edit from the setup preview first.")
    if field not in editable_fields(draft):
        raise ValueError("That field cannot be edited for this market.")
    draft["editing"] = True
    draft["edit_field"] = field
    draft["step"] = field
    return draft


def back(draft):
    if not is_wizard(draft):
        raise ValueError("No setup wizard is active.")
    if draft.get("step") == "edit":
        draft["step"] = "preview"
        return draft
    if draft.get("editing"):
        step = draft.get("step")
        edit_field = draft.get("edit_field")
        if edit_field == "market" and step == "symbol":
            draft["step"] = "other_market" if draft.get("answers", {}).get("market_kind") == "Other" else "market"
        elif edit_field == "market" and step == "other_market":
            draft["step"] = "market"
        elif edit_field == "timeframe" and step == "timeframe_other":
            draft["step"] = "timeframe"
        elif edit_field == "expiry" and step == "expiry_other":
            draft["step"] = "expiry"
        else:
            draft["step"] = "edit"
            draft.pop("editing", None)
            draft.pop("edit_field", None)
        return draft
    history = draft.setdefault("history", [])
    if not history:
        raise ValueError("You are already at the first question.")
    draft["step"] = history.pop()
    return draft


def market_label(draft):
    answers = draft.get("answers", {})
    kind = answers.get("market_kind", "")
    market = answers.get("other_market", "") if kind == "Other" else kind
    symbol = answers.get("symbol", "")
    return f"{market} ({symbol})" if symbol else market


def storage_market(draft):
    answers = draft.get("answers", {})
    kind = answers.get("market_kind", "")
    market = answers.get("other_market", "") if kind == "Other" else kind
    symbol = answers.get("symbol", "")
    return f"{market}/{symbol}" if symbol else market


def preview_text(draft):
    answers = draft.get("answers", {})
    timeframe = answers.get("timeframe") or "Not specified"
    confirmation = answers.get("confirmation") or "Not specified"
    direction = draft.get("poi_direction")
    poi = f"🎯 POI type: {direction}\n" if direction else ""
    approximate = "Approx. " if draft.get("approximate_zone") else ""
    behavior = (
        "This will be added as an independent active zone; existing zones stay active."
        if draft.get("independent") else
        "This will replace the selected active zone after review."
        if draft.get("replaces_setup_id") else
        "This will be reviewed as a zone post before publishing."
    )
    return (
        "📍 SETUP DETAILS — REVIEW\n\n"
        f"📊 Market: {market_label(draft)}\n"
        f"{poi}"
        f"⬇️ Lower zone price: {approximate}{answers.get('low', 'Not entered')}\n"
        f"⬆️ Upper zone price: {approximate}{answers.get('high', 'Not entered')}\n"
        f"⏱️ Timeframe: {timeframe}\n"
        f"✅ Required confirmation: {confirmation}\n"
        "⌛ Expiry: Manual — this zone stays active until you mark it expired.\n\n"
        f"{behavior}\n"
        "Confirm saves these details as a draft and continues to the chart step. "
        "It does not publish a message."
    )


def build_setup(draft):
    answers = draft.get("answers", {})
    required = ("market_kind", "low", "high")
    if any(not answers.get(key) for key in required):
        raise ValueError("Complete the market and both zone prices before confirming.")
    if answers.get("market_kind") == "Other" and not answers.get("other_market"):
        raise ValueError("Enter the name of the other market.")
    market = storage_market(draft)
    if not market:
        raise ValueError("Choose a market before confirming.")
    setup = parse_zone(
        f"{market} | {answers['low']}-{answers['high']} | "
        f"{answers.get('timeframe') or '-'} | manual | "
        f"{answers.get('confirmation') or '-'}"
    )
    if draft.get("poi_direction"):
        setup["poi_direction"] = draft["poi_direction"]
    if draft.get("approximate_zone"):
        setup["approximate_zone"] = True
    return setup
