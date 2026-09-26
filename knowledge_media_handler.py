from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters, Application

from config import ADMIN_ID
from knowledge import add_project_file, get_project, get_project_file_count, get_session, MAX_FILES_PER_PROJECT


def _photo_name(update: Update) -> str:
    caption = (update.effective_message.caption or "").strip()
    if caption:
        safe = " ".join(caption.split())[:80]
        return f"{safe}.jpg"
    message_id = update.effective_message.message_id
    return f"photo_{message_id}.jpg"


async def handle_knowledge_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    session = get_session(ADMIN_ID)
    if not session or not session.get("project_id"):
        return

    project_id = session["project_id"]
    if get_project_file_count(project_id) >= MAX_FILES_PER_PROJECT:
        await update.effective_message.reply_text(
            f"⚠️ В проекте уже максимум {MAX_FILES_PER_PROJECT} материалов."
        )
        return

    photo = update.effective_message.photo[-1]
    file_name = _photo_name(update)

    try:
        add_project_file(
            project_id,
            photo.file_id,
            file_name,
            "image/jpeg",
        )
    except ValueError as exc:
        await update.effective_message.reply_text(f"⚠️ {exc}")
        return

    project = get_project(project_id)
    count = get_project_file_count(project_id)

    await update.effective_message.reply_text(
        f"🖼️ Фото добавлено: {file_name}\n\n"
        f"📁 {project['name']}\n"
        f"📎 Материалов: {count}/{MAX_FILES_PER_PROJECT}\n\n"
        "Можно отправить следующий файл/фото или нажать «✅ Готово».",
        reply_markup=__import__('knowledge').build_files_keyboard(),
    )


def install(bot_module):
    original_add_handler = Application.add_handler
    installed_apps = set()

    def patched_add_handler(self, handler, group=0):
        app_id = id(self)
        if app_id not in installed_apps:
            original_add_handler(
                self,
                MessageHandler(
                    filters.PHOTO,
                    handle_knowledge_photo,
                ),
                group=-1,
            )
            installed_apps.add(app_id)
        return original_add_handler(self, handler, group)

    Application.add_handler = patched_add_handler
