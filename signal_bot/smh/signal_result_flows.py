"""Administrator-only, resumable result screenshot flow for published signals."""
import asyncio
from html import escape
from pathlib import Path

from .database import uid
from .domain import safe_text
from .images import import_chart, render_signal_capture
from .signal_results import (
    OUTCOME_LABELS,
    default_result_caption,
    telegram_message_link,
    validate_result_caption,
)


class SignalResultFlows:
    def _result_record(self, trade_id):
        trade = self.db.trade(trade_id)
        if not trade.get("message_id"):
            raise ValueError("This trade has no confirmed published signal yet.")
        record = self.db.signal_result(trade_id)
        if not record:
            record, _ = self.db.create_signal_result(trade_id, self.config.admin)
        if record.get("status") == "awaiting_signal":
            record = self.db.update_signal_result(
                trade_id,
                {
                    "status": "pending",
                    "signal_message_id": trade.get("message_id"),
                    "zone_message_id": trade.get("setup_message_id"),
                    "signal_text": trade.get("original_text", ""),
                },
                expected_statuses=("awaiting_signal",),
            )
        operation_id = record.get("operation_id")
        if record.get("status") == "publishing" and not operation_id:
            # No send can begin until the operation id is durably attached.
            record = self.db.update_signal_result(
                trade_id, {"status": "ready"}, expected_statuses=("publishing",))
        if record.get("status") in ("ready", "publishing") and operation_id:
            operation, _payload = self.publisher.operation(operation_id)
            if operation["status"] == "done":
                record = self.db.update_signal_result(
                    trade_id,
                    {"status": "posted", "analysis_message_id": operation.get("message_id")},
                    expected_statuses=("ready", "publishing"),
                )
            elif operation["status"] in ("uncertain", "sending"):
                record = self.db.update_signal_result(
                    trade_id, {"status": "uncertain"},
                    expected_statuses=("ready", "publishing"))
            elif operation["status"] in ("prepared", "retryable") and record.get("status") == "publishing":
                record = self.db.update_signal_result(
                    trade_id, {"status": "ready"}, expected_statuses=("publishing",))
            elif operation["status"] == "failed":
                record = self.db.update_signal_result(
                    trade_id, {"status": "ready", "operation_id": ""},
                    expected_statuses=("ready", "publishing"))
        return trade, record

    def _result_buttons(self, record):
        trade_id, updated = record["trade_id"], record["updated"]
        return [
            [("📸 Capture Signal Screenshot", "signal_result_capture",
              {"trade_id": trade_id, "updated": updated})],
            [("🖼️ Attach Result Screenshot", "signal_result_attach",
              {"trade_id": trade_id, "updated": updated}),
             ("🧾 Set / Change Result", "signal_result_choose",
              {"trade_id": trade_id, "updated": updated})],
            [("👁️ Preview Analysis Post", "signal_result_preview",
              {"trade_id": trade_id, "updated": updated}),
             ("📤 Post Result to Market Analysis Group", "signal_result_confirm_screen",
              {"trade_id": trade_id, "updated": updated})],
            [("⏳ Save for Later", "signal_result_save",
              {"trade_id": trade_id, "updated": updated}),
             ("❌ Cancel", "signal_result_cancel",
              {"trade_id": trade_id, "updated": updated})],
        ]

    async def signal_results_list(self, update):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        records = [
            item for item in self.db.signal_results()
            if item.get("status") in ("pending", "ready", "publishing", "uncertain")
            and item.get("signal_message_id")
        ]
        buttons = [
            (f"{item.get('symbol', 'Signal')} · {item.get('direction', '')} · "
             f"{'Needs review' if item.get('status') != 'posted' else 'Posted'}",
             "signal_result_open", {"trade_id": item["trade_id"]})
            for item in records[:20]
        ]
        buttons.append(("↩️ Trade Management", "admin_category", {"category": "trades"}))
        text = "📤 PENDING MARKET ANALYSIS RESULTS\n\n"
        if records:
            text += "Open a saved result to attach its screenshot, review, or continue a pending post."
        else:
            text += "There are no saved result screenshots waiting to be reviewed."
        return await self.say(update, text, buttons, admin_chrome=False)

    async def signal_result_screen(self, update, trade_id, notice=None):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        status_text = {
            "pending": "Waiting for a result screenshot and your confirmed result selection.",
            "ready": "Screenshot and result are saved and ready for review.",
            "publishing": "The Market Analysis post is being checked.",
            "uncertain": "The send result is uncertain. Check Market Analysis before taking further action.",
            "posted": "The approved result screenshot was posted to Market Analysis.",
            "awaiting_signal": "The original signal is not yet confirmed as published.",
        }.get(record.get("status"), "Open the saved result to review it.")
        caption = (
            "<b>📤 SIGNAL RESULT — PRIVATE REVIEW</b>\n\n"
            f"<b>Market:</b> {escape(str(trade.get('symbol') or trade.get('market') or 'Not recorded'))}\n"
            f"<b>Direction:</b> {escape(str(trade.get('direction') or 'Not recorded'))}\n"
            f"<b>Entry:</b> {escape(str(trade.get('entry') or 'Not recorded'))}\n"
            f"<b>Stop Loss:</b> {escape(str(trade.get('sl') or 'Not recorded'))}\n"
            f"<b>Take Profit:</b> {escape(_format_targets(trade.get('targets', {})))}\n"
            f"<b>Result status:</b> {escape(status_text)}\n"
            f"<b>Result screenshot:</b> {'attached' if record.get('profit_image') else 'not attached'}\n"
            f"<b>Confirmed result:</b> {escape(OUTCOME_LABELS.get(record.get('outcome'), 'not selected'))}"
        )
        zone_link = telegram_message_link(self.config.signals, trade.get("setup_message_id"))
        if zone_link:
            caption += f'\n\n<a href="{escape(zone_link, quote=True)}">Open original trading zone</a>'
        else:
            caption += "\n\nOriginal trading-zone link is unavailable for this saved message."
        analysis_link = telegram_message_link(
            self.config.analysis, record.get("analysis_message_id"))
        if analysis_link:
            caption += f'\n<a href="{escape(analysis_link, quote=True)}">Open published Analysis result</a>'
        if notice:
            caption = f"<b>{escape(notice)}</b>\n\n" + caption

        operation_pending = False
        if record.get("operation_id"):
            operation, _payload = self.publisher.operation(record["operation_id"])
            operation_pending = operation["status"] in ("prepared", "retryable")
        if operation_pending:
            rows = [
                [("👁️ Preview Analysis Post", "signal_result_preview",
                  {"trade_id": trade_id, "updated": record["updated"]}),
                 ("📤 Review Post Again", "signal_result_confirm_screen",
                  {"trade_id": trade_id, "updated": record["updated"]})],
                [("⏳ Save for Later", "signal_result_save",
                  {"trade_id": trade_id, "updated": record["updated"]}),
                 ("❌ Cancel", "signal_result_cancel",
                  {"trade_id": trade_id, "updated": record["updated"]})],
                [("📋 Pending Result Posts", "signal_results_list", {})],
            ]
        elif record.get("status") in ("posted", "uncertain", "publishing", "awaiting_signal"):
            rows = [
                [("📸 Capture Signal Screenshot", "signal_result_capture",
                  {"trade_id": trade_id, "updated": record["updated"]})],
                [("📋 Pending Result Posts", "signal_results_list", {})],
                [("↩️ Trade Management", "admin_category", {"category": "trades"})],
            ]
        else:
            rows = self._result_buttons(record)
            rows.append([("📋 Pending Result Posts", "signal_results_list", {})])
        return await self.say_rows(update, caption, rows, parse_mode="HTML")

    async def signal_result_capture(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        path = await asyncio.to_thread(
            render_signal_capture, record.get("signal_text", ""), self.db.directory / "images")
        image_data = {"signal_capture": path}
        self.db.persist_images(image_data)
        record = self.db.update_signal_result(
            trade_id, {"signal_capture": image_data["signal_capture"]},
            expected_updated=expected_updated,
        )
        link = telegram_message_link(self.config.signals, trade.get("setup_message_id"))
        note = (
            "<b>📸 PUBLISHED SIGNAL — PRIVATE CAPTURE</b>\n"
            f"<b>Market:</b> {escape(str(trade.get('symbol') or trade.get('market') or 'Not recorded'))}\n"
            f"<b>Direction:</b> {escape(str(trade.get('direction') or 'Not recorded'))}\n"
            f"<b>Entry:</b> {escape(str(trade.get('entry') or 'Not recorded'))}\n"
            f"<b>Stop Loss:</b> {escape(str(trade.get('sl') or 'Not recorded'))}\n"
            f"<b>Take Profit:</b> {escape(_format_targets(trade.get('targets', {})))}\n"
        )
        note += (f'<a href="{escape(link, quote=True)}">Open original trading zone</a>'
                 if link else "Original trading-zone link unavailable.")
        image_path = self.db.image_path(record["signal_capture"])
        with open(image_path, "rb") as image_file:
            await self.bot.send_photo(
                update.effective_chat.id, image_file, caption=note, parse_mode="HTML")
        return await self.signal_result_screen(
            update, trade_id, notice="Signal screenshot saved privately.")

    async def signal_result_attach(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        _require_result_editable(self.publisher, record)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("This result is already posted or needs delivery reconciliation.")
        draft = {
            "kind": "signal_result_upload",
            "step": "photo",
            "trade_id": trade_id,
            "updated": record["updated"],
        }
        self.db.save_draft(update.effective_user.id, draft)
        return await self.say(
            update,
            "🖼️ Send the result screenshot here as a photo or image file. "
            "It will be saved privately against this signal and will not be posted yet.",
            [("❌ Cancel Upload", "signal_result_cancel",
              {"trade_id": trade_id, "updated": record["updated"]})],
            admin_chrome=False,
        )

    async def save_signal_result_screenshot(self, update):
        user = update.effective_user.id
        self.config.authorize(user, update.effective_chat.type)
        draft = self.db.draft(user)
        if (not draft or draft.get("kind") != "signal_result_upload" or
                draft.get("step") != "photo"):
            raise ValueError("Open the saved result and choose Attach Result Screenshot first.")
        trade_id = draft.get("trade_id")
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, draft.get("updated"))
        _require_result_editable(self.publisher, record)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("This result is already posted or needs delivery reconciliation.")
        photo = getattr(update.message, "photo", None)
        document = getattr(update.message, "document", None)
        item = photo[-1] if photo else document
        if not item:
            raise ValueError("Send one JPEG, PNG, or WEBP screenshot.")
        if document and getattr(item, "mime_type", "") not in (
                "image/jpeg", "image/png", "image/webp"):
            raise ValueError("Send the screenshot as a JPEG, PNG, or WEBP image.")
        if item.file_size and item.file_size > 10 * 1024 * 1024:
            raise ValueError("The screenshot must be 10 MB or smaller.")
        remote_file = await item.get_file()
        raw = self.db.directory / "images" / f"{uid()}.upload"
        try:
            await remote_file.download_to_drive(raw)
            imported = await asyncio.to_thread(
                import_chart, raw, self.db.directory / "images")
            image_data = {"profit_image": imported}
            self.db.persist_images(image_data)
            outcome = record.get("outcome")
            status = "ready" if outcome in OUTCOME_LABELS else "pending"
            self.db.update_signal_result(
                trade_id,
                {"profit_image": image_data["profit_image"], "status": status},
                expected_statuses=("pending", "ready"),
            )
        finally:
            raw.unlink(missing_ok=True)
        self.db.clear_draft(user)
        return await self.signal_result_screen(
            update, trade_id, notice="Screenshot saved privately. It has not been published.")

    async def signal_result_choose(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        _require_result_editable(self.publisher, record)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("The saved result can no longer be edited.")
        buttons = [
            (label, "signal_result_outcome", {
                "trade_id": trade_id, "updated": record["updated"], "outcome": key,
            })
            for key, label in OUTCOME_LABELS.items()
        ]
        buttons += [
            ("↩️ Back to Result", "signal_result_open", {"trade_id": trade_id}),
            ("❌ Cancel", "signal_result_cancel",
             {"trade_id": trade_id, "updated": record["updated"]}),
        ]
        return await self.say(
            update,
            "Choose only the result you have confirmed from the screenshot. "
            "“Not stated” avoids making a profit or loss claim.",
            buttons,
            admin_chrome=False,
        )

    async def signal_result_set_outcome(self, update, trade_id, expected_updated, outcome):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        if outcome not in OUTCOME_LABELS or record.get("status") not in ("pending", "ready"):
            raise ValueError("Choose a valid result for an editable saved post.")
        caption = default_result_caption(trade["direction"], outcome)
        status = "ready" if record.get("profit_image") else "pending"
        self.db.update_signal_result(
            trade_id,
            {"outcome": outcome, "caption": caption, "status": status},
            expected_updated=expected_updated,
            expected_statuses=("pending", "ready"),
        )
        return await self.signal_result_screen(
            update, trade_id, notice=f"Result saved as {OUTCOME_LABELS[outcome]}.")

    async def signal_result_edit_caption(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        _require_result_editable(self.publisher, record)
        if record.get("status") not in ("pending", "ready") or record.get("outcome") not in OUTCOME_LABELS:
            raise ValueError("Select a confirmed result before editing the post caption.")
        self.db.save_draft(update.effective_user.id, {
            "kind": "signal_result_caption",
            "step": "caption",
            "trade_id": trade_id,
            "updated": record["updated"],
        })
        return await self.say(
            update,
            f"Type the caption you want to use. Keep these exact lines so the saved signal and result stay clear:\n"
            f"Direction: {trade_direction(record)}\n"
            f"Result: {OUTCOME_LABELS[record['outcome']]}\n\n"
            "The caption will be checked for specific trade instructions and previewed before publishing.",
            [("❌ Cancel Caption Edit", "signal_result_cancel",
              {"trade_id": trade_id, "updated": record["updated"]})],
            admin_chrome=False,
        )

    async def signal_result_caption_text(self, update, draft, text):
        trade_id = draft.get("trade_id")
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, draft.get("updated"))
        _require_result_editable(self.publisher, record)
        caption = validate_result_caption(safe_text(text, 900), trade["direction"], record["outcome"])
        status = "ready" if record.get("profit_image") else "pending"
        self.db.update_signal_result(
            trade_id, {"caption": caption, "status": status},
            expected_statuses=("pending", "ready"),
        )
        self.db.clear_draft(update.effective_user.id)
        return await self.signal_result_screen(
            update, trade_id, notice="Caption saved. Review the exact post before publishing.")

    def _public_result_caption(self, trade, record):
        caption = record.get("caption") or default_result_caption(
            trade["direction"], record.get("outcome"))
        caption = validate_result_caption(caption, trade["direction"], record["outcome"])
        internal_ids = (
            record.get("id"), record.get("trade_id"), record.get("setup_id"),
            record.get("operation_id"), record.get("signal_message_id"),
            record.get("zone_message_id"),
        )
        caption = self._clean_result_caption(caption, internal_ids)
        return validate_result_caption(caption, trade["direction"], record["outcome"])

    @staticmethod
    def _clean_result_caption(caption, internal_ids):
        from .publishing import clean_channel_text
        return clean_channel_text(caption, internal_ids)

    async def signal_result_preview(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("This result is posted or awaiting delivery reconciliation.")
        if not record.get("profit_image") or record.get("outcome") not in OUTCOME_LABELS:
            return await self.signal_result_screen(
                update, trade_id,
                notice="Attach a screenshot and confirm its result before opening a publish preview.")
        caption = self._public_result_caption(trade, record)
        if record.get("status") != "ready" or record.get("caption") != caption:
            record = self.db.update_signal_result(
                trade_id, {"caption": caption, "status": "ready"},
                expected_statuses=("pending", "ready"),
            )
        return await self._show_result_preview(update, trade, record, final=False)

    async def signal_result_confirm_screen(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("This result is posted or awaiting delivery reconciliation.")
        if not record.get("profit_image") or record.get("outcome") not in OUTCOME_LABELS:
            return await self.signal_result_screen(
                update, trade_id,
                notice="Attach a screenshot and choose the result before reviewing publication.")
        caption = self._public_result_caption(trade, record)
        if record.get("status") != "ready" or record.get("caption") != caption:
            record = self.db.update_signal_result(
                trade_id, {"caption": caption, "status": "ready"},
                expected_statuses=("pending", "ready"),
            )
        return await self._show_result_preview(update, trade, record, final=True)

    async def _show_result_preview(self, update, trade, record, *, final):
        image_path = self.db.image_path(record["profit_image"])
        with open(image_path, "rb") as image_file:
            await self.bot.send_photo(
                update.effective_chat.id, image_file,
                caption="Final review only — not posted." if final else "Preview only — not posted.")
        heading = "FINAL CONFIRMATION" if final else "PREVIEW — NOT PUBLISHED"
        text = (f"👁️ <b>{heading}</b>\n\nExact Market Analysis caption:\n\n"
                f"{escape(record['caption'])}")
        trade_id, updated = record["trade_id"], record["updated"]
        if final:
            buttons = [
                [("✅ Confirm & Publish to Market Analysis Group", "signal_result_publish_confirm",
                  {"trade_id": trade_id, "updated": updated})],
                [("✏️ Edit Caption", "signal_result_edit_caption",
                  {"trade_id": trade_id, "updated": updated}),
                 ("↔️ Change Result", "signal_result_choose",
                  {"trade_id": trade_id, "updated": updated})],
                [("⏳ Save for Later", "signal_result_save",
                  {"trade_id": trade_id, "updated": updated}),
                 ("❌ Cancel", "signal_result_cancel",
                  {"trade_id": trade_id, "updated": updated})],
            ]
        else:
            buttons = [
                [("📤 Publish to Market Analysis Group", "signal_result_confirm_screen",
                  {"trade_id": trade_id, "updated": updated})],
                [("✏️ Edit Caption", "signal_result_edit_caption",
                  {"trade_id": trade_id, "updated": updated}),
                 ("↔️ Change Result", "signal_result_choose",
                  {"trade_id": trade_id, "updated": updated})],
                [("⏳ Save for Later", "signal_result_save",
                  {"trade_id": trade_id, "updated": updated}),
                 ("❌ Cancel", "signal_result_cancel",
                  {"trade_id": trade_id, "updated": updated})],
            ]
        return await self.say_rows(update, text, buttons, parse_mode="HTML")

    async def signal_result_publish_confirm(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        if record.get("status") == "posted":
            return await self.signal_result_screen(update, trade_id, notice="This result was already posted.")
        if record.get("status") == "uncertain":
            return await self.signal_result_screen(
                update, trade_id, notice="Check Market Analysis and reconcile the existing operation; do not resend.")
        if record.get("status") != "ready":
            raise ValueError("Open the complete final preview before confirming.")
        # Fail closed before prepare/send can reach Telegram.
        if not self.config.allow_publishing:
            return await self.signal_result_screen(
                update, trade_id, notice="Publishing is OFF. No Market Analysis post was prepared or sent.")
        if not self.publisher.verified:
            return await self.signal_result_screen(
                update, trade_id, notice="Publishing verification is incomplete. No post was prepared or sent.")
        if not self.config.ready:
            return await self.signal_result_screen(
                update, trade_id, notice="The configured channel destinations are incomplete. No post was sent.")
        caption = self._public_result_caption(trade, record)
        if not record.get("profit_image"):
            raise ValueError("Attach the reviewed result screenshot before confirming.")
        payload = {
            "destination": "analysis",
            "text": caption,
            "image": record["profit_image"],
        }
        operation_id = record.get("operation_id")
        if operation_id:
            operation, old_payload = self.publisher.operation(operation_id)
            if operation["status"] == "done":
                return await self.signal_result_screen(
                    update, trade_id, notice="This result was already posted; it will not be duplicated.")
            if operation["status"] in ("uncertain", "sending"):
                self.db.update_signal_result(
                    trade_id, {"status": "uncertain"}, expected_statuses=("ready",))
                return await self.signal_result_screen(
                    update, trade_id, notice="The send result is uncertain. Check Market Analysis before proceeding.")
            if operation["status"] == "failed":
                self.db.update_signal_result(
                    trade_id, {"operation_id": "", "status": "ready"},
                    expected_statuses=("ready",),
                )
                return await self.signal_result_screen(
                    update, trade_id,
                    notice="Telegram rejected the previous attempt. Review the post again before a new attempt.")
            if operation["status"] not in ("prepared", "retryable"):
                raise ValueError("Resolve the existing result operation before publishing.")
            if (old_payload.get("text") != caption or
                    old_payload.get("image") != record["profit_image"] or
                    old_payload.get("channel") != self.config.analysis):
                raise ValueError("The saved operation differs from this preview. Review it before any new send.")
            self.db.update_signal_result(
                trade_id, {"status": "publishing"},
                expected_updated=expected_updated,
                expected_statuses=("ready",),
            )
        else:
            self.db.update_signal_result(
                trade_id, {"status": "publishing"},
                expected_updated=expected_updated,
                expected_statuses=("ready",),
            )
            try:
                operation_id = self.publisher.prepare(
                    update.effective_user.id, "analysis", payload)
            except ValueError as exc:
                latest = self.db.signal_result(trade_id)
                if latest and latest.get("status") == "publishing":
                    self.db.update_signal_result(
                        trade_id, {"status": "ready"},
                        expected_statuses=("publishing",),
                    )
                return await self.signal_result_screen(
                    update, trade_id, notice=f"Post was not prepared: {exc}")
            self.db.update_signal_result(
                trade_id,
                {"operation_id": operation_id, "status": "publishing"},
                expected_statuses=("publishing",),
            )

        try:
            outcome = await self.publisher.send(update.effective_user.id, operation_id)
        except Exception:
            operation, _payload = self.publisher.operation(operation_id)
            if operation["status"] in ("uncertain", "sending"):
                status = "uncertain"
                notice = "Telegram’s delivery result is uncertain. Check Market Analysis before doing anything else."
            elif operation["status"] == "failed":
                status = "ready"
                notice = "Telegram rejected the post. No automatic retry was made; review it before trying again."
                self.db.update_signal_result(
                    trade_id, {"operation_id": "", "status": status},
                    expected_statuses=("publishing",),
                )
                return await self.signal_result_screen(update, trade_id, notice=notice)
            else:
                status = "ready"
                notice = "The post was not confirmed. Review the saved operation before another attempt."
            self.db.update_signal_result(
                trade_id, {"status": status}, expected_statuses=("publishing",))
            return await self.signal_result_screen(update, trade_id, notice=notice)

        operation, _payload = self.publisher.operation(operation_id)
        if operation["status"] == "done":
            self.db.update_signal_result(
                trade_id,
                {"status": "posted", "analysis_message_id": operation.get("message_id")},
                expected_statuses=("publishing",),
            )
            return await self.signal_result_screen(
                update, trade_id, notice="Result screenshot published to Market Analysis.")
        if operation["status"] == "retryable":
            self.db.update_signal_result(
                trade_id, {"status": "ready"}, expected_statuses=("publishing",))
            return await self.signal_result_screen(
                update, trade_id,
                notice="Telegram rate-limited the post. The same saved operation can be retried after its wait.")
        self.db.update_signal_result(
            trade_id, {"status": "uncertain"}, expected_statuses=("publishing",))
        return await self.signal_result_screen(
            update, trade_id, notice=f"Post status needs review: {outcome}")

    async def signal_result_save(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        if record.get("status") not in ("pending", "ready"):
            raise ValueError("This result cannot be saved as a draft in its current state.")
        draft = self.db.draft(update.effective_user.id)
        if draft and draft.get("trade_id") == trade_id and draft.get("kind", "").startswith("signal_result"):
            self.db.clear_draft(update.effective_user.id)
        return await self.signal_result_screen(
            update, trade_id, notice="Saved for later. Nothing was posted.")

    async def signal_result_cancel(self, update, trade_id, expected_updated):
        self.config.authorize(update.effective_user.id, update.effective_chat.type)
        _trade, record = self._result_record(trade_id)
        _check_result_revision(record, expected_updated)
        draft = self.db.draft(update.effective_user.id)
        if draft and draft.get("trade_id") == trade_id and draft.get("kind", "").startswith("signal_result"):
            self.db.clear_draft(update.effective_user.id)
        return await self.signal_result_screen(
            update, trade_id, notice="Cancelled this step. The saved result remains available; nothing was posted.")


def trade_direction(record):
    return str(record.get("direction") or "Not recorded")


def _check_result_revision(record, expected_updated):
    if not expected_updated or record.get("updated") != expected_updated:
        raise ValueError("This result changed. Reopen it and review the latest version.")


def _require_result_editable(publisher, record):
    if record.get("operation_id"):
        operation, _payload = publisher.operation(record["operation_id"])
        if operation["status"] in ("prepared", "retryable", "sending", "uncertain", "done"):
            raise ValueError(
                "A result-post operation already exists. Resolve or retry that exact post before editing it.")


def _format_targets(targets):
    if not isinstance(targets, dict) or not targets:
        return "Not recorded"
    values = []
    def sort_key(item):
        try:
            return (0, int(item[0]))
        except (TypeError, ValueError):
            return (1, str(item[0]))

    for number, target in sorted(targets.items(), key=sort_key):
        value = target.get("price") if isinstance(target, dict) else target
        if value is not None:
            values.append(f"TP{number}: {value}")
    return ", ".join(values) or "Not recorded"
