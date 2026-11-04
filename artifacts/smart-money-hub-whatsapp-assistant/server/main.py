from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl

from assistant import providers, storage

BASE_PATH = os.environ.get(
    "WHATSAPP_APP_BASE_PATH", "/smart-money-hub-whatsapp-assistant"
).rstrip("/")
API_PREFIX = f"{BASE_PATH}/api"
WEBHOOK_PATH = f"{BASE_PATH}/webhooks/whatsapp"
SESSION_COOKIE = "smh_whatsapp_admin"
SESSION_TTL_SECONDS = 8 * 60 * 60
IS_TEST_ENV = os.environ.get("APP_ENV") == "test"
COOKIE_SECURE = not IS_TEST_ENV
login_attempts: dict[str, list[float]] = {}


class AdminLogin(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AdminReply(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class EducationModuleUpdate(BaseModel):
    summary: str = Field(max_length=2000)
    content: str = Field(max_length=50000)
    published: bool


class WhatsAppSettingsUpdate(BaseModel):
    paused: bool | None = None
    telegramCommunityUrl: HttpUrl | None = None


def _session_key() -> bytes:
    raw = os.environ.get("WHATSAPP_SESSION_SECRET") or os.environ.get("SESSION_SECRET", "")
    if not raw and IS_TEST_ENV:
        raw = "test-only-session-key"
    return raw.encode("utf-8")


def _session_value() -> str:
    exp = str(int(time.time()) + SESSION_TTL_SECONDS)
    nonce = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
    payload = f"{exp}.{nonce}"
    signature = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _valid_session(value: str | None) -> bool:
    if not value or not _session_key():
        return False
    try:
        exp_text, nonce, supplied = value.split(".", 2)
        payload = f"{exp_text}.{nonce}"
        expected = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
        return int(exp_text) > int(time.time()) and hmac.compare_digest(expected, supplied)
    except (ValueError, TypeError):
        return False


def _password_configured() -> bool:
    return bool(os.environ.get("WHATSAPP_ADMIN_PASSWORD", "").strip())


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")
    if not origin or not host:
        raise HTTPException(status_code=403, detail="A same-origin admin request is required.")
    parsed = urlparse(origin)
    if parsed.netloc.lower() != host.lower() or parsed.scheme not in {"https", "http"}:
        raise HTTPException(status_code=403, detail="Cross-origin admin requests are not allowed.")


async def require_admin(request: Request) -> None:
    if not _valid_session(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Admin sign-in required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _same_origin(request)


def _connection_status() -> dict[str, Any]:
    return providers.connection_status()


def _dashboard_data() -> dict[str, Any]:
    return {
        "paused": storage.get_setting("paused", "0") == "1",
        "testMode": True,
        **storage.dashboard_counts(),
        "recentActivity": storage.recent_activity(8),
        "connection": _connection_status(),
    }


async def _send_reply(conversation_id: int, recipient: str, text: str) -> dict[str, Any]:
    if not providers.test_mode():
        raise HTTPException(status_code=403, detail="Outbound sending is locked to test mode.")
    if providers.normalize_wa_id(recipient) not in providers.allowed_test_recipients():
        raise HTTPException(status_code=403, detail="This recipient is not on the test allowlist.")
    message_id = await providers.send_text(recipient, text)
    storage.add_outbound(conversation_id, message_id, text)
    storage.add_activity("outbound", "A test reply was sent.")
    return message_id


def _is_within_customer_window(value: str | None) -> bool:
    if not value:
        return False
    try:
        last_inbound = datetime.fromisoformat(value)
        if last_inbound.tzinfo is None:
            last_inbound = last_inbound.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_inbound).total_seconds() < 24 * 60 * 60
    except ValueError:
        return False


async def _process_inbound_queue() -> None:
    while True:
        row = storage.claim_next_inbound()
        if row is None:
            await asyncio.sleep(0.75)
            continue
        message_id = int(row["id"])
        conversation_id = int(row["conversation_id"])
        recipient = str(row["wa_id"])
        inbound_text = str(row["text"])
        try:
            if storage.get_setting("paused", "0") == "1":
                storage.finish_inbound(message_id, "paused")
                continue
            if recipient not in providers.allowed_test_recipients():
                storage.finish_inbound(message_id, "blocked")
                storage.add_activity("blocked", "An inbound sender was outside the test allowlist.")
                continue
            if not providers.connection_status()["credentialsConfigured"]:
                storage.finish_inbound(message_id, "blocked")
                storage.add_activity("setup", "A test reply was held until WhatsApp credentials are configured.")
                continue
            if not _is_within_customer_window(str(row["last_inbound_at"])):
                storage.finish_inbound(message_id, "expired")
                storage.add_activity("attention", "An inbound message was outside the reply window.")
                continue

            is_new = not bool(row["welcome_sent"])
            if is_new:
                # Persist before sending to avoid an automatic duplicate welcome after a restart.
                storage.mark_welcome_sent(conversation_id)
                welcome_id = await providers.send_text(recipient, providers.WELCOME)
                storage.add_outbound(conversation_id, welcome_id, providers.WELCOME)

            reply, is_enquiry = providers.menu_reply(inbound_text)
            if is_enquiry:
                storage.mark_enquiry(conversation_id)
            if reply is None:
                if is_new and providers.is_greeting(inbound_text):
                    storage.finish_inbound(message_id, "sent")
                    continue
                modules = storage.list_modules(published_only=True)
                history = storage.recent_messages(conversation_id)
                reply = await providers.generate_answer(inbound_text, history, modules)
            if reply:
                await _send_reply(conversation_id, recipient, reply)
            storage.finish_inbound(message_id, "sent")
        except providers.ProviderError:
            storage.finish_inbound(message_id, "failed")
            storage.add_activity("attention", "A test reply could not be delivered; review the conversation.")
        except Exception:
            # Error text, request payloads, phone numbers and provider response bodies are not logged.
            storage.finish_inbound(message_id, "failed")
            storage.add_activity("attention", "A message could not be processed; review the conversation.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init_db()
    storage.mark_interrupted_processing()
    task = asyncio.create_task(_process_inbound_queue())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Smart Money Hub WhatsApp Assistant",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get(f"{API_PREFIX}/whatsapp/health")
async def whatsapp_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(f"{API_PREFIX}/whatsapp/auth/me")
async def auth_status(request: Request) -> dict[str, bool]:
    return {
        "authenticated": _valid_session(request.cookies.get(SESSION_COOKIE)),
        "passwordConfigured": _password_configured(),
    }


@app.post(f"{API_PREFIX}/whatsapp/auth/login")
async def admin_login(payload: AdminLogin, request: Request, response: Response) -> dict[str, bool]:
    _same_origin(request)
    if not _password_configured() or not _session_key():
        raise HTTPException(status_code=503, detail="Admin sign-in is not configured.")
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = [stamp for stamp in login_attempts.get(ip, []) if now - stamp < 15 * 60]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again later.")
    attempts.append(now)
    login_attempts[ip] = attempts
    configured = os.environ["WHATSAPP_ADMIN_PASSWORD"]
    if not hmac.compare_digest(payload.password, configured):
        raise HTTPException(status_code=401, detail="Invalid sign-in details.")
    login_attempts.pop(ip, None)
    response.set_cookie(
        SESSION_COOKIE,
        _session_value(),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path=BASE_PATH,
    )
    return {"authenticated": True, "passwordConfigured": True}


@app.post(f"{API_PREFIX}/whatsapp/auth/logout", status_code=204)
async def admin_logout(response: Response, _: None = Depends(require_admin)) -> Response:
    response.delete_cookie(SESSION_COOKIE, path=BASE_PATH, httponly=True, secure=COOKIE_SECURE, samesite="strict")
    response.status_code = 204
    return response


@app.get(f"{API_PREFIX}/whatsapp/dashboard")
async def dashboard(_: None = Depends(require_admin)) -> dict[str, Any]:
    return _dashboard_data()


@app.get(f"{API_PREFIX}/whatsapp/activity")
async def activity(_: None = Depends(require_admin)) -> list[dict[str, Any]]:
    return storage.recent_activity(30)


@app.get(f"{API_PREFIX}/whatsapp/conversations")
async def conversations(
    search: str = "",
    enquiriesOnly: bool = False,
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    return storage.list_conversations(
        search=search,
        enquiries_only=enquiriesOnly,
        test_recipients=providers.allowed_test_recipients(),
    )


@app.get(f"{API_PREFIX}/whatsapp/conversations/{{conversation_id}}")
async def conversation(conversation_id: int, _: None = Depends(require_admin)) -> dict[str, Any]:
    result = storage.get_conversation(
        conversation_id,
        test_recipients=providers.allowed_test_recipients(),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return result


@app.post(f"{API_PREFIX}/whatsapp/conversations/{{conversation_id}}/reply")
async def reply_to_conversation(
    conversation_id: int,
    payload: AdminReply,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    row = storage.conversation_by_id(conversation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if not _is_within_customer_window(row["last_inbound_at"]):
        raise HTTPException(status_code=403, detail="The 24-hour reply window is closed.")
    if not providers.test_mode():
        raise HTTPException(status_code=403, detail="Outbound sending is locked to test mode.")
    if providers.normalize_wa_id(row["wa_id"]) not in providers.allowed_test_recipients():
        raise HTTPException(status_code=403, detail="This recipient is not on the test allowlist.")
    try:
        provider_id = await providers.send_text(row["wa_id"], payload.text)
    except providers.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    outbound_id = storage.add_outbound(conversation_id, provider_id, payload.text)
    storage.add_activity("admin_reply", "An admin reply was sent to a test conversation.")
    return {
        "id": outbound_id,
        "direction": "outbound",
        "text": payload.text,
        "status": "sent",
        "createdAt": storage.utc_now(),
    }


@app.get(f"{API_PREFIX}/whatsapp/education-modules")
async def education_modules(_: None = Depends(require_admin)) -> list[dict[str, Any]]:
    return storage.list_modules()


@app.put(f"{API_PREFIX}/whatsapp/education-modules/{{slug}}")
async def update_education_module(
    slug: str,
    payload: EducationModuleUpdate,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    result = storage.update_module(slug, payload.summary, payload.content, payload.published)
    if result is None:
        raise HTTPException(status_code=404, detail="Education module not found.")
    storage.add_activity("content", f"Education content updated: {result['title']}.")
    return result


@app.get(f"{API_PREFIX}/whatsapp/settings")
async def settings(request: Request, _: None = Depends(require_admin)) -> dict[str, Any]:
    return {
        "paused": storage.get_setting("paused", "0") == "1",
        "testMode": True,
        "telegramCommunityUrl": storage.get_setting("telegram_community_url") or None,
        "webhookUrl": f"{str(request.base_url).rstrip('/')}{WEBHOOK_PATH}",
        "connection": _connection_status(),
    }


@app.patch(f"{API_PREFIX}/whatsapp/settings")
async def update_settings(
    request: Request,
    payload: WhatsAppSettingsUpdate,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    if payload.paused is not None:
        storage.set_paused(payload.paused)
    if "telegramCommunityUrl" in payload.model_fields_set:
        link = str(payload.telegramCommunityUrl) if payload.telegramCommunityUrl else ""
        if link:
            parsed = urlparse(link)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in {"t.me", "telegram.me"}
                or parsed.path.startswith(("/c/", "/s/"))
            ):
                raise HTTPException(status_code=422, detail="Use a public HTTPS Telegram invite link.")
        storage.put_setting("telegram_community_url", link)
        storage.add_activity("settings", "The Telegram community link was updated.")
    return {
        "paused": storage.get_setting("paused", "0") == "1",
        "testMode": True,
        "telegramCommunityUrl": storage.get_setting("telegram_community_url") or None,
        "webhookUrl": f"{str(request.base_url).rstrip('/')}{WEBHOOK_PATH}",
        "connection": _connection_status(),
    }


@app.get(WEBHOOK_PATH)
async def verify_webhook(request: Request) -> PlainTextResponse:
    params = request.query_params
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Webhook verification failed.")
    if len(challenge) > 2048:
        raise HTTPException(status_code=400, detail="Invalid webhook challenge.")
    return PlainTextResponse(challenge)


@app.post(WEBHOOK_PATH)
async def receive_webhook(request: Request) -> dict[str, bool]:
    try:
        declared_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared_length = 0
    if declared_length > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    body = await request.body()
    if not providers.verify_meta_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="Webhook signature verification failed.")
    if len(body) > 1_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                str(item.get("wa_id", "")): item.get("profile", {}).get("name")
                for item in value.get("contacts", [])
            }
            for message in value.get("messages", []):
                wa_id = providers.normalize_wa_id(str(message.get("from", "")))
                provider_id = str(message.get("id", ""))
                if not wa_id or not provider_id:
                    continue
                message_type = str(message.get("type", "unsupported"))
                if message_type == "text":
                    text = str(message.get("text", {}).get("body", "")).strip()
                elif message_type == "interactive":
                    interactive = message.get("interactive", {})
                    selected = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    text = str(selected.get("title") or selected.get("id") or "").strip()
                else:
                    text = ""
                if not text:
                    text = "I received a non-text message. Please send your question as text."
                try:
                    storage.record_inbound(
                        provider_id=provider_id,
                        wa_id=wa_id,
                        display_name=contacts.get(wa_id),
                        text=text,
                    )
                except Exception:
                    # Avoid recording payload details or phone numbers in logs.
                    storage.add_activity("attention", "A webhook message could not be stored.")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "23826")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
