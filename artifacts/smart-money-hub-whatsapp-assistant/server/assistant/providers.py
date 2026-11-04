from __future__ import annotations

import hmac
import os
import re
import uuid
from typing import Any

import httpx

from . import storage

GEMINI_MODEL = "gemini-3.5-flash-lite"
GRAPH_API_VERSION = os.environ.get("WHATSAPP_GRAPH_API_VERSION", "v25.0").strip()
GRAPH_API_ROOT = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

WELCOME = (
    "Welcome to Smart Money Hub. I’m the AI learning assistant. "
    "Your messages may be processed by AI to prepare replies. Please don’t send passwords "
    "or account credentials.\n\n"
    "Choose a topic or type a question:\n"
    "1. Trading Fundamentals\n"
    "2. Smart Money Concepts\n"
    "3. Gold Trading (XAUUSD)\n"
    "4. Join Free Classes\n"
    "5. Telegram Community\n"
    "6. Ask the AI Coach\n"
    "7. Speak to an Admin"
)


class ProviderError(Exception):
    """Provider call failed without exposing credentials or raw provider payloads."""


def normalize_wa_id(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def allowed_test_recipients() -> set[str]:
    raw = os.environ.get("WHATSAPP_TEST_RECIPIENTS", "")
    return {normalize_wa_id(item) for item in raw.split(",") if normalize_wa_id(item)}


def test_mode() -> bool:
    # This build is intentionally locked to Meta's test-number workflow.
    return True


def connection_status() -> dict[str, Any]:
    access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    app_secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    recipients = allowed_test_recipients()
    return {
        "credentialsConfigured": bool(access_token and phone_id),
        "webhookConfigured": bool(app_secret and verify_token),
        "geminiConfigured": bool(gemini_key),
        "allowedTestRecipients": len(recipients),
    }


def verify_meta_signature(body: bytes, signature: str | None) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, "sha256").hexdigest()
    return hmac.compare_digest(expected, signature)


async def send_text(recipient: str, text: str) -> str:
    normalized = normalize_wa_id(recipient)
    if not test_mode() or normalized not in allowed_test_recipients():
        raise ProviderError("Recipient is not on the configured test allowlist.")

    token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not token or not phone_id:
        raise ProviderError("WhatsApp test credentials are not configured.")
    if not GRAPH_API_VERSION or not re.fullmatch(r"v\d+\.\d+", GRAPH_API_VERSION):
        raise ProviderError("WhatsApp Graph API version is not configured.")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
            response = await client.post(
                f"{GRAPH_API_ROOT}/{phone_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            message_id = data.get("messages", [{}])[0].get("id")
            if not message_id:
                raise ProviderError("WhatsApp did not confirm the test message.")
            return str(message_id)
    except ProviderError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        # Never log or forward provider response bodies, headers, or credentials.
        raise ProviderError("WhatsApp could not send the test message.") from exc


def resource_link() -> str:
    return storage.get_setting("telegram_community_url").strip()


def menu_reply(text: str) -> tuple[str | None, bool]:
    normalized = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    normalized = " ".join(normalized.split())
    choices = {
        "1": ("trading-fundamentals", "Trading Fundamentals"),
        "2": ("smart-money-concepts", "Smart Money Concepts"),
        "3": ("gold-xauusd", "Gold Trading (XAUUSD)"),
    }
    if normalized in choices:
        slug, _ = choices[normalized]
        module = next((item for item in storage.list_modules(published_only=True) if item["slug"] == slug), None)
        return (module["content"] if module and module["content"] else None), False
    if normalized in {"4", "5"} or any(
        term in normalized
        for term in (
            "join free classes",
            "join free class",
            "join a class",
            "free classes",
            "telegram community",
            "community link",
            "join community",
        )
    ):
        link = resource_link()
        if link:
            return f"Here is the Smart Money Hub Telegram community link: {link}", False
        return "The Telegram community link has not been added yet. I’ve flagged this for the admin.", True
    if normalized == "6":
        return "Send your question in your own words and I’ll help with the educational topic.", False
    if (
        normalized in {"7", "admin", "human", "support"}
        or "speak to admin" in normalized
        or "talk to admin" in normalized
        or "need a person" in normalized
    ):
        return "I’ve flagged this conversation for the admin. You can add a short note about what you need.", True
    return None, False


def is_greeting(text: str) -> bool:
    normalized = re.sub(r"[^a-z ]", " ", text.lower())
    normalized = " ".join(normalized.split())
    return normalized in {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "start", "menu", "help", "1", "2", "3", "4", "5", "6", "7",
    }


def local_answer(question: str, modules: list[dict[str, Any]]) -> str:
    terms = {
        "market-structure": ("market structure", "bos", "choch", "structure"),
        "liquidity": ("liquidity", "sweep", "equal high", "equal low"),
        "points-of-interest": ("poi", "point of interest", "zone", "entry"),
        "order-blocks": ("order block", "ob"),
        "fair-value-gaps": ("fvg", "fair value gap", "imbalance"),
        "premium-discount": ("premium", "discount", "midpoint"),
        "gold-xauusd": ("gold", "xauusd", "xau"),
        "risk-management": ("risk", "stop loss", "invalidation"),
        "trading-psychology": ("psychology", "journal", "discipline"),
        "smart-money-concepts": ("smc", "smart money"),
        "trading-fundamentals": ("plan", "trading fundamentals"),
    }
    question_lower = question.lower()
    for slug, keywords in terms.items():
        if any(keyword in question_lower for keyword in keywords):
            module = next(
                (item for item in modules if item["slug"] == slug and item["published"]),
                None,
            )
            if module:
                return module["content"]
    return (
        "I can help with market structure, liquidity, points of interest, order blocks, "
        "fair value gaps, gold education, and risk management. Which one are you asking about?"
    )


async def generate_answer(
    question: str,
    history: list[dict[str, str]],
    modules: list[dict[str, Any]],
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return local_answer(question, modules)
    reference = "\n\n".join(
        f"{item['title']}: {item['content']}"
        for item in modules
        if item["published"] and item["content"].strip()
    )[:24000]
    system_instruction = (
        "You are the Smart Money Hub AI learning assistant. Be natural, clear, concise, "
        "and follow the conversation's topic instead of jumping to an unrelated lesson. "
        "Use the supplied Smart Money Hub learning notes as your primary reference. "
        "Explain trading education only; never provide personalized trade signals, promise "
        "profits, or claim to know live prices, current news, or a live market view. "
        "If asked for current data, say you cannot verify it here and suggest checking a "
        "reliable current source. If the notes do not support a specific claim, say so and "
        "ask one focused clarifying question. Do not call the user CEO. Avoid repetitive "
        "disclaimers and do not repeat the whole welcome menu."
        "\n\nApproved learning notes:\n" + reference
    )
    contents: list[dict[str, Any]] = []
    for item in history[-12:]:
        role = "model" if item["role"] == "assistant" else "user"
        if item["text"].strip():
            contents.append({"role": role, "parts": [{"text": item["text"][:4096]}]})
    if not contents or contents[-1]["role"] != "user":
        contents.append({"role": "user", "parts": [{"text": question[:4096]}]})

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18.0, connect=5.0)) as client:
            response = await client.post(
                GEMINI_ENDPOINT,
                headers={"x-goog-api-key": api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": contents,
                    "generationConfig": {"temperature": 0.35, "maxOutputTokens": 500},
                },
            )
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            answer = "".join(part.get("text", "") for part in parts).strip()
            if not answer or len(answer) > 4096:
                raise ProviderError("The assistant returned no usable answer.")
            return answer
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, ProviderError):
        return local_answer(question, modules)


def opaque_message_id(prefix: str = "local") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"
