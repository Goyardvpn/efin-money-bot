"""Надёжное подключение базы знаний и навигации к Application."""

from telegram import ReplyKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

import knowledge
from knowledge_media_handler import handle_knowledge_photo

_installed = False
_original_run_polling = None
_original_handle_message = None

NAVIGATION_TEXTS = {
    "🤖 Efin AI",
    "👤 Личный кабинет",
    "🛠 Админ-панель",
    "⬅️ Выйти",
    "📚 База знаний",
}


async def _knowledge_first_message(update, context):
    """Перехватывает только текст администратора, когда активна KB-сессия."""
    if not update.message or not update.effective_user:
        return False

    admin_id = update.effective_user.id
    if admin_id != knowledge.ADMIN_ID:
        return False

    session = knowledge.get_session(admin_id)
    if not session:
        return False

    text = (update.message.text or "").strip()
    if text in NAVIGATION_TEXTS:
        knowledge.finish_session(admin_id)
        return False

    await knowledge.handle_knowledge_text(update, context)
    return True


async def _navigation_priority_handler(update, context):
    """Приоритетная навигация до parser/AI/старых обработчиков."""
    if not update.message or not update.effective_user or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "⬅️ Выйти":
        knowledge.finish_session(user_id)
        try:
            import ai_feature
            ai_feature.AI_SESSIONS.discard(user_id)
        except Exception:
            pass

        import bot
        handler = getattr(bot, "handle_message", None)
        if handler is not None:
            return await handler(update, context)
        return

    if text == "📚 База знаний" and user_id == knowledge.ADMIN_ID:
        knowledge.finish_session(user_id)
        await update.message.reply_text(
            "📚 Управление базой знаний:",
            reply_markup=knowledge.build_admin_projects_keyboard(),
        )
        return


async def _knowledge_document_priority_handler(update, context):
    """Файлы KB идут раньше parser/AI и не должны теряться среди MessageHandler-ов."""
    if not update.message or not update.effective_user or not update.message.document:
        return
    if update.effective_user.id != knowledge.ADMIN_ID:
        return
    if not knowledge.get_session(knowledge.ADMIN_ID):
        return

    await knowledge.handle_knowledge_document(update, context)


async def _knowledge_photo_priority_handler(update, context):
    """Фото KB идут отдельным приоритетным обработчиком."""
    if not update.message or not update.effective_user or not update.message.photo:
        return
    if update.effective_user.id != knowledge.ADMIN_ID:
        return
    if not knowledge.get_session(knowledge.ADMIN_ID):
        return

    await handle_knowledge_photo(update, context)


def _add_knowledge_handlers(application):
    if application.bot_data.get("_efin_knowledge_handlers"):
        return

    knowledge.init_knowledge_db()

    # Группа -300: KB-сессия имеет абсолютный приоритет над parser/AI.
    # Навигация при этом остаётся отдельным маршрутом.
    application.add_handler(
        MessageHandler(
            filters.TEXT & filters.Regex(r"^(⬅️ Выйти|📚 База знаний)$"),
            _navigation_priority_handler,
        ),
        group=-300,
    )

    application.add_handler(
        MessageHandler(
            filters.Document.ALL & filters.User(knowledge.ADMIN_ID),
            _knowledge_document_priority_handler,
        ),
        group=-300,
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO & filters.User(knowledge.ADMIN_ID),
            _knowledge_photo_priority_handler,
        ),
        group=-300,
    )

    application.add_handler(
        MessageHandler(
            knowledge.KnowledgeTextFilter(),
            knowledge.handle_knowledge_text,
        ),
        group=-300,
    )

    application.add_handler(
        CallbackQueryHandler(
            knowledge.handle_knowledge_callback,
            pattern=r"^(kb_|admin_kb_)",
        ),
        group=-200,
    )

    application.bot_data["_efin_knowledge_handlers"] = True
    print("[Efin KB] Обработчики базы знаний подключены напрямую к Application")


def _patch_admin_menu(bot_module):
    keyboard = getattr(bot_module.ADMIN_PANEL_MENU, "keyboard", None)
    rows = [list(row) for row in (keyboard or [])]

    if not any("📚 База знаний" in row for row in rows):
        insert_at = len(rows)
        for index, row in enumerate(rows):
            if "⬅️ Назад" in row:
                insert_at = index
                break
        rows.insert(insert_at, ["📚 База знаний"])

    bot_module.ADMIN_PANEL_MENU = ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def install(bot_module):
    global _installed, _original_run_polling, _original_handle_message

    if _installed:
        return

    knowledge.init_knowledge_db()
    _patch_admin_menu(bot_module)

    if hasattr(bot_module, "handle_message"):
        _original_handle_message = bot_module.handle_message

        async def handle_message_with_knowledge(update, context):
            handled = await _knowledge_first_message(update, context)
            if handled:
                return
            return await _original_handle_message(update, context)

        bot_module.handle_message = handle_message_with_knowledge

    _original_run_polling = Application.run_polling

    def run_polling_with_knowledge(self, *args, **kwargs):
        _add_knowledge_handlers(self)
        return _original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_knowledge
    _installed = True
    print("[Efin KB] Надёжный bootstrap базы знаний активирован")
