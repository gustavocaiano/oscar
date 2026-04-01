from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from personal_assistant_bot.ai import AIBackendError, AIResponse, OpenAICompatibleAI
from personal_assistant_bot.config import Settings
from personal_assistant_bot.hours import parse_getmm
from personal_assistant_bot.services import AssistantError, AssistantService, PendingApproval
from personal_assistant_bot.storage import ListItem, NoteItem, ReminderItem


logger = logging.getLogger(__name__)

APPROVAL_CALLBACK_PATTERN = re.compile(r"^(approve|reject):([0-9a-f]+)$")


ROOT_COMMANDS = [
    BotCommand("start", "Show welcome message"),
    BotCommand("help", "Show grouped command help"),
    BotCommand("task", "Task commands"),
    BotCommand("shop", "Shopping list commands"),
    BotCommand("note", "Notes and inbox commands"),
    BotCommand("rem", "Reminder commands"),
    BotCommand("cal", "Calendar commands"),
    BotCommand("h", "Hour tracking commands"),
    BotCommand("pref", "Preference commands"),
    BotCommand("confirm", "Confirm a pending AI action"),
    BotCommand("reject", "Reject a pending AI action"),
]


class PersonalAssistantBot:
    def __init__(self, *, settings: Settings, assistant: AssistantService, ai_client: OpenAICompatibleAI):
        self.settings = settings
        self.assistant = assistant
        self.ai_client = ai_client

    def build_application(self) -> Application:
        application = ApplicationBuilder().token(self.settings.telegram_bot_token).post_init(self._post_init).build()
        application.add_handler(CommandHandler("start", self.start_handler))
        application.add_handler(CommandHandler("help", self.help_handler))
        application.add_handler(CommandHandler("task", self.task_handler))
        application.add_handler(CommandHandler("shop", self.shop_handler))
        application.add_handler(CommandHandler("note", self.note_handler))
        application.add_handler(CommandHandler("rem", self.reminder_handler))
        application.add_handler(CommandHandler("cal", self.calendar_handler))
        application.add_handler(CommandHandler("h", self.hours_handler))
        application.add_handler(CommandHandler("pref", self.preference_handler))
        application.add_handler(CommandHandler("confirm", self.confirm_handler))
        application.add_handler(CommandHandler("reject", self.reject_handler))
        application.add_handler(CallbackQueryHandler(self.approval_callback_handler, pattern=r"^(approve|reject):"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.chat_handler))
        application.add_error_handler(self.error_handler)
        application.job_queue.run_repeating(self.scheduler_tick, interval=self.settings.reminder_scan_seconds, first=10)
        return application

    async def _post_init(self, application: Application) -> None:
        await application.bot.set_my_commands(ROOT_COMMANDS)

    async def start_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._ensure_access(update):
            return
        await update.effective_message.reply_text(self._help_text())

    async def help_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not await self._ensure_access(update):
            return
        await update.effective_message.reply_text(self._help_text())

    async def task_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        await self._handle_list_root(update, context, kind="task")

    async def shop_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        await self._handle_list_root(update, context, kind="shopping")

    async def note_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text(
                "Use /note add <text>, /note inbox <text>, /note list [count], or /note search <query>."
            )
            return
        subcommand = context.args[0].lower()
        rest = context.args[1:]
        try:
            if subcommand == "add":
                note_id = self.assistant.add_note(chat_id=chat_id, user_id=user_id, kind="note", content=" ".join(rest))
                await update.effective_message.reply_text(f"Saved note #{note_id}")
                return
            if subcommand == "inbox":
                note_id = self.assistant.add_note(chat_id=chat_id, user_id=user_id, kind="inbox", content=" ".join(rest))
                await update.effective_message.reply_text(f"Saved inbox item #{note_id}")
                return
            if subcommand == "list":
                limit = int(rest[0]) if rest and rest[0].isdigit() else 10
                notes = self.assistant.list_notes(chat_id=chat_id, user_id=user_id, limit=limit)
                await update.effective_message.reply_text(self._format_notes(notes))
                return
            if subcommand == "search":
                notes = self.assistant.list_notes(chat_id=chat_id, user_id=user_id, limit=10, query=" ".join(rest))
                await update.effective_message.reply_text(self._format_notes(notes))
                return
            raise AssistantError("Unknown /note subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def reminder_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text(
                "Use /rem add YYYY-MM-DD HH:MM | text, /rem list, /rem done <id>, or /rem cancel <id>."
            )
            return
        subcommand = context.args[0].lower()
        rest = " ".join(context.args[1:])
        try:
            if subcommand == "add":
                parts = self._split_pipe(rest, minimum=2)
                reminder_id = self.assistant.create_reminder(
                    chat_id=chat_id, user_id=user_id, due_text=parts[0], message=parts[1]
                )
                await update.effective_message.reply_text(f"Created reminder #{reminder_id}")
                return
            if subcommand == "list":
                reminders = self.assistant.list_reminders(chat_id=chat_id, user_id=user_id, pending_only=False)
                await update.effective_message.reply_text(self._format_reminders(reminders, chat_id, user_id))
                return
            if subcommand in {"done", "cancel"}:
                if not context.args[1:]:
                    raise AssistantError("Please provide a reminder id")
                reminder_id = int(context.args[1])
                status = "done" if subcommand == "done" else "cancelled"
                self.assistant.update_reminder(chat_id=chat_id, user_id=user_id, reminder_id=reminder_id, status=status)
                await update.effective_message.reply_text(f"Reminder #{reminder_id} marked {status}")
                return
            raise AssistantError("Unknown /rem subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def calendar_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text(
                "Use /cal list [days] or /cal add YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM | title [| description]."
            )
            return
        subcommand = context.args[0].lower()
        try:
            if subcommand == "list":
                days = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 7
                events = self.assistant.list_calendar_events(chat_id=chat_id, user_id=user_id, days=days)
                if not events:
                    await update.effective_message.reply_text("No upcoming events found.")
                    return
                preferences = self.assistant.ensure_chat(chat_id=chat_id, user_id=user_id)
                lines = ["Upcoming events:"]
                for event in events[:10]:
                    all_day = getattr(event, "all_day", False)
                    if all_day:
                        if getattr(event, "start_date", None) is not None:
                            label = event.start_date.isoformat()
                        else:
                            start_value = event.start
                            if start_value.tzinfo is None:
                                start_value = start_value.replace(tzinfo=ZoneInfo(preferences.timezone))
                            label = start_value.astimezone(ZoneInfo(preferences.timezone)).strftime('%Y-%m-%d')
                        lines.append(f"- {label} — {event.summary} (all day)")
                    else:
                        start_local = event.start
                        end_local = event.end
                        if start_local.tzinfo is None:
                            start_local = start_local.replace(tzinfo=ZoneInfo(preferences.timezone))
                        if end_local.tzinfo is None:
                            end_local = end_local.replace(tzinfo=ZoneInfo(preferences.timezone))
                        start_local = start_local.astimezone(ZoneInfo(preferences.timezone))
                        end_local = end_local.astimezone(ZoneInfo(preferences.timezone))
                        lines.append(
                            f"- {start_local.strftime('%Y-%m-%d %H:%M')} to {end_local.strftime('%H:%M')} — {event.summary}"
                        )
                await update.effective_message.reply_text("\n".join(lines))
                return
            if subcommand == "add":
                parts = self._split_pipe(" ".join(context.args[1:]), minimum=3)
                description = parts[3] if len(parts) > 3 else None
                event = self.assistant.create_calendar_event(
                    chat_id=chat_id,
                    user_id=user_id,
                    start_text=parts[0],
                    end_text=parts[1],
                    summary=parts[2],
                    description=description,
                )
                await update.effective_message.reply_text(
                    f"Created calendar event: {event.summary} ({event.start.strftime('%Y-%m-%d %H:%M')})"
                )
                return
            raise AssistantError("Unknown /cal subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def hours_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text("Use /h add <hours> or /h month [MM].")
            return
        subcommand = context.args[0].lower()
        try:
            if subcommand == "add":
                result = self.assistant.add_hours(chat_id=chat_id, user_id=user_id, raw_text=" ".join(context.args[1:]))
                await update.effective_message.reply_text(result)
                return
            if subcommand == "month":
                month = None
                if len(context.args) > 1:
                    if context.args[1].startswith("get"):
                        month = parse_getmm(context.args[1])
                    else:
                        month = int(context.args[1])
                await update.effective_message.reply_text(
                    self.assistant.get_month_hours(chat_id=chat_id, user_id=user_id, month=month)
                )
                return
            raise AssistantError("Unknown /h subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def preference_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text(
                "Use /pref show, /pref enable <morning|hours|evening|reminders>, /pref disable <...>, /pref time <morning|hours|evening> HH:MM, or /pref timezone <Zone>"
            )
            return
        subcommand = context.args[0].lower()
        try:
            if subcommand == "show":
                await update.effective_message.reply_text(
                    self.assistant.get_preferences_summary(chat_id=chat_id, user_id=user_id)
                )
                return
            if subcommand in {"enable", "disable"}:
                if len(context.args) < 2:
                    raise AssistantError("Please specify a preference key")
                result = self.assistant.update_preference_toggle(
                    chat_id=chat_id,
                    user_id=user_id,
                    key=context.args[1].lower(),
                    enabled=subcommand == "enable",
                )
                await update.effective_message.reply_text(result)
                return
            if subcommand == "time":
                if len(context.args) < 3:
                    raise AssistantError("Use /pref time <morning|hours|evening> HH:MM")
                result = self.assistant.update_preference_time(
                    chat_id=chat_id,
                    user_id=user_id,
                    key=context.args[1].lower(),
                    time_value=context.args[2],
                )
                await update.effective_message.reply_text(result)
                return
            if subcommand == "timezone":
                if len(context.args) < 2:
                    raise AssistantError("Use /pref timezone <Area/Location>")
                result = self.assistant.update_timezone(
                    chat_id=chat_id,
                    user_id=user_id,
                    timezone_name=context.args[1],
                )
                await update.effective_message.reply_text(result)
                return
            raise AssistantError("Unknown /pref subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def confirm_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text("Use /confirm <token>")
            return
        try:
            result = self.assistant.confirm_approval(chat_id=chat_id, user_id=user_id, token=context.args[0])
            await update.effective_message.reply_text(result)
        except AssistantError as exc:
            await update.effective_message.reply_text(str(exc))

    async def reject_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        chat_id, user_id = self._chat_and_user(update)
        if not context.args:
            await update.effective_message.reply_text("Use /reject <token>")
            return
        try:
            result = self.assistant.reject_approval(chat_id=chat_id, user_id=user_id, token=context.args[0])
            await update.effective_message.reply_text(result)
        except AssistantError as exc:
            await update.effective_message.reply_text(str(exc))

    async def approval_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        query = update.callback_query
        if query is None:
            return

        action_token = self._parse_approval_callback_data(query.data)
        if action_token is None:
            await query.answer("Invalid approval action.", show_alert=True)
            return

        action, token = action_token
        if update.effective_chat is None or update.effective_user is None:
            await query.answer("This approval request is missing chat context.", show_alert=True)
            return
        if self.settings.allowed_chat_ids and update.effective_chat.id not in self.settings.allowed_chat_ids:
            await query.answer("This bot is not enabled for this chat.", show_alert=True)
            return

        try:
            if action == "approve":
                result = self.assistant.confirm_approval(
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                    token=token,
                )
                final_text = f"✅ Approved — {result}"
            else:
                result = self.assistant.reject_approval(
                    chat_id=update.effective_chat.id,
                    user_id=update.effective_user.id,
                    token=token,
                )
                final_text = f"❌ Rejected — {result}"
        except AssistantError as exc:
            await query.answer(str(exc), show_alert=True)
            return

        await query.answer("Action processed.")
        if query.message is not None:
            await query.edit_message_text(final_text)

    async def chat_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_access(update):
            return
        if update.effective_message is None or update.effective_message.text is None:
            return
        chat_id, user_id = self._chat_and_user(update)
        user_message = update.effective_message.text.strip()
        if not user_message:
            return
        if not self.ai_client.configured:
            await update.effective_message.reply_text(
                "AI chat is not configured yet. Deterministic commands still work."
            )
            return

        self.assistant.ensure_chat(chat_id=chat_id, user_id=user_id)
        self.assistant.add_chat_history(chat_id=chat_id, user_id=user_id, role="user", content=user_message)
        history = self.assistant.get_chat_history(chat_id=chat_id, user_id=user_id)
        snapshot = self.assistant.get_tool_snapshot(chat_id=chat_id, user_id=user_id)

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            ai_result = await self.ai_client.respond(user_message=user_message, history=history, tool_snapshot=snapshot)
        except AIBackendError as exc:
            logger.warning("AI backend failure: %s", exc)
            await update.effective_message.reply_text(str(exc))
            return

        reply_text = ai_result.reply
        reply_markup = None
        if ai_result.proposed_action:
            approval = self.assistant.create_pending_approval(
                chat_id=chat_id,
                user_id=user_id,
                action_type=str(ai_result.proposed_action["action_type"]),
                payload=dict(ai_result.proposed_action.get("payload") or {}),
                prompt_text=str(ai_result.proposed_action.get("label") or ai_result.reply),
            )
            reply_text = (
                f"{ai_result.reply}\n\n"
                f"Proposed action: {approval.prompt_text}\n"
                f"Use the buttons below, or fallback to /confirm {approval.token} / /reject {approval.token}."
            )
            reply_markup = self._build_approval_keyboard(approval)

        self.assistant.add_chat_history(chat_id=chat_id, user_id=user_id, role="assistant", content=reply_text)
        await update.effective_message.reply_text(reply_text, reply_markup=reply_markup)

    async def scheduler_tick(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        notifications = self.assistant.get_due_notifications(now_utc=datetime.now(timezone.utc))
        for notification in notifications:
            try:
                await context.bot.send_message(chat_id=notification.chat_id, text=notification.text)
                self.assistant.mark_notification_delivered(notification)
            except Exception:
                logger.exception("Failed to deliver scheduled notification to chat %s", notification.chat_id)
                self.assistant.revert_notification_claim(notification)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled bot error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message is not None:
            await update.effective_message.reply_text("An unexpected error occurred.")

    async def _handle_list_root(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *, kind: str) -> None:
        chat_id, user_id = self._chat_and_user(update)
        singular = "task" if kind == "task" else "shopping item"
        if not context.args:
            action_word = "buy" if kind == "shopping" else "done"
            await update.effective_message.reply_text(
                f"Use /{'shop' if kind == 'shopping' else 'task'} add <text>, /{'shop' if kind == 'shopping' else 'task'} list, /{'shop' if kind == 'shopping' else 'task'} {action_word} <id>, or /{'shop' if kind == 'shopping' else 'task'} rename <id> | <new title>."
            )
            return

        subcommand = context.args[0].lower()
        rest = " ".join(context.args[1:])
        try:
            if subcommand == "add":
                titles = [part.strip() for part in rest.split(",") if part.strip()]
                item_ids = self.assistant.create_items(chat_id=chat_id, user_id=user_id, kind=kind, titles=titles)
                await update.effective_message.reply_text(f"Created {len(item_ids)} {kind} item(s)")
                return
            if subcommand == "list":
                items = self.assistant.list_items(chat_id=chat_id, user_id=user_id, kind=kind, include_done=False)
                await update.effective_message.reply_text(self._format_list_items(items, singular=singular))
                return
            if subcommand in {"done", "buy"}:
                if len(context.args) < 2:
                    raise AssistantError(f"Please provide a {singular} id")
                self.assistant.complete_item(
                    chat_id=chat_id, user_id=user_id, kind=kind, item_id=int(context.args[1])
                )
                await update.effective_message.reply_text(f"Marked {singular} #{int(context.args[1])} complete")
                return
            if subcommand == "rename":
                if len(context.args) < 2:
                    raise AssistantError(f"Use /{'shop' if kind == 'shopping' else 'task'} rename <id> | <new title>")
                parts = self._split_pipe(rest, minimum=2)
                self.assistant.rename_item(
                    chat_id=chat_id,
                    user_id=user_id,
                    kind=kind,
                    item_id=int(parts[0]),
                    title=parts[1],
                )
                await update.effective_message.reply_text(f"Renamed {singular} #{int(parts[0])}")
                return
            raise AssistantError(f"Unknown /{'shop' if kind == 'shopping' else 'task'} subcommand")
        except (AssistantError, ValueError) as exc:
            await update.effective_message.reply_text(str(exc))

    async def _ensure_access(self, update: Update) -> bool:
        if update.effective_chat is None:
            return False
        if not self.settings.allowed_chat_ids or update.effective_chat.id in self.settings.allowed_chat_ids:
            return True
        if update.effective_message is not None:
            await update.effective_message.reply_text("This bot is not enabled for this chat.")
        return False

    def _chat_and_user(self, update: Update) -> tuple[int, int]:
        if update.effective_chat is None or update.effective_user is None:
            raise AssistantError("Telegram update is missing chat or user information")
        return update.effective_chat.id, update.effective_user.id

    def _split_pipe(self, raw_text: str, *, minimum: int) -> list[str]:
        parts = [part.strip() for part in raw_text.split("|")]
        if len(parts) < minimum or any(not part for part in parts[:minimum]):
            raise AssistantError("Please separate arguments with '|' characters")
        return parts

    def _help_text(self) -> str:
        return (
            "Personal assistant commands:\n\n"
            "/task add Buy milk\n"
            "/task list\n"
            "/task done 3\n"
            "/shop add eggs, bread\n"
            "/shop list\n"
            "/shop buy 2\n"
            "/note add Idea text\n"
            "/note inbox Something to remember\n"
            "/note list\n"
            "/note search passport\n"
            "/rem add 2026-04-01 09:00 | Call the bank\n"
            "/rem list\n"
            "/cal list 7\n"
            "/cal add 2026-04-01 14:00 | 2026-04-01 15:00 | Dentist\n"
            "/h add 2h 30m\n"
            "/h month 04\n"
            "/pref show\n"
            "AI approval buttons are shown automatically; /confirm TOKEN and /reject TOKEN remain as fallback.\n\n"
            "If you send a normal message, the assistant uses AI chat mode, can inspect your assistant data, and asks before writing changes."
        )

    def _build_approval_keyboard(self, approval: PendingApproval) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Confirm", callback_data=f"approve:{approval.token}"),
                    InlineKeyboardButton("Deny", callback_data=f"reject:{approval.token}"),
                ]
            ]
        )

    def _parse_approval_callback_data(self, raw_data: str | None) -> tuple[str, str] | None:
        if not raw_data:
            return None
        match = APPROVAL_CALLBACK_PATTERN.fullmatch(raw_data)
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _format_list_items(self, items: Iterable[ListItem], *, singular: str) -> str:
        items = list(items)
        if not items:
            return f"No open {singular}s."
        lines = [f"Open {singular}s:"]
        for item in items:
            lines.append(f"- #{item.id} {item.title}")
        return "\n".join(lines)

    def _format_notes(self, notes: Iterable[NoteItem]) -> str:
        notes = list(notes)
        if not notes:
            return "No notes found."
        lines = ["Notes:"]
        for note in notes:
            lines.append(f"- #{note.id} [{note.kind}] {note.content}")
        return "\n".join(lines)

    def _format_reminders(self, reminders: Iterable[ReminderItem], chat_id: int, user_id: int) -> str:
        reminders = list(reminders)
        if not reminders:
            return "No reminders found."
        preferences = self.assistant.ensure_chat(chat_id=chat_id, user_id=user_id)
        lines = ["Reminders:"]
        for reminder in reminders:
            try:
                local_due = datetime.fromisoformat(reminder.due_at).astimezone(ZoneInfo(preferences.timezone))
                due_label = local_due.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                due_label = reminder.due_at[:16].replace("T", " ")
            lines.append(
                f"- #{reminder.id} [{reminder.status}] {reminder.message} @ {due_label} ({preferences.timezone})"
            )
        return "\n".join(lines)
