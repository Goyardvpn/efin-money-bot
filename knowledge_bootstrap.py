"""Надёжное подключение базы знаний к Application после создания приложения."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

import knowledge
from knowledge_media_handler import handle_knowledge_photo


_installed = False
_original_run_polling = None


def _add_knowledge_handlers(application):
    """Добавляет обработчики базы знаний ровно один раз на экземпляр Application."""
    if application.bot_data.get("_efin_knowledge_handlers"):
        return

    knowledge.init_knowledge_db()

    # Callback-кнопки базы знаний имеют приоритет над обычной админкой.
    application.add_handler(
        CallbackQueryHandler(
            knowledge.handle_knowledge_callback,
            pattern=r"^(kb_|admin_kb_)" ,
        ),
        group=-100,
    )

    # Тексты активной сессии базы знаний имеют приоритет над parser.py.
    application.add_handler(
        MessageHandler(
            knowledge.KnowledgeTextFilter(),
            knowledge.handle_knowledge_text,
        ),
        group=-100,
    )

    application.add_handler(
        MessageHandler(
            knowledge.KnowledgeDocumentFilter(),
            knowledge.handle_knowledge_document,
        ),
        group=-100,
    )

    # Фото в активной сессии добавляются как отдельный материал.
    application.add_handler(
        MessageHandler(
            filters.PHOTO & filters.User(knowledge.ADMIN_ID),
            handle_knowledge_photo,
        ),
        group=-100,
    )

    application.bot_data["_efin_knowledge_handlers"] = True
    print("[Efin KB] Обработчики базы знаний подключены напрямую к Application")


def _patch_admin_menu(bot_module):
    """Добавляет кнопку базы знаний в существующую админ-панель."""
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
    global _installed, _original_run_polling

    if _installed:
        return

    knowledge.init_knowledge_db()
    _patch_admin_menu(bot_module)

    _original_run_polling = Application.run_polling

    def run_polling_with_knowledge(self, *args, **kwargs):
        _add_knowledge_handlers(self)
        return _original_run_polling(self, *args, **kwargs)

    Application.run_polling = run_polling_with_knowledge
    _installed = True
    print("[Efin KB] Надёжный bootstrap базы знаний активирован")
