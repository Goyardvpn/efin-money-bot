from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

from config import ADMIN_ID
from database import get_connection

MAX_FILES_PER_PROJECT = 10
KB_SESSIONS = {}


def init_knowledge_db():
    with get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                file_id TEXT,
                file_name TEXT,
                mime_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, file_id),
                FOREIGN KEY(project_id) REFERENCES knowledge_projects(id) ON DELETE CASCADE
            )"""
        )
        old = conn.execute(
            "SELECT id, file_id, file_name, mime_type FROM knowledge_projects WHERE file_id IS NOT NULL"
        ).fetchall()
        for row in old:
            conn.execute(
                """INSERT OR IGNORE INTO knowledge_files(project_id,file_id,file_name,mime_type)
                   VALUES(?,?,?,?)""",
                (row["id"], row["file_id"], row["file_name"] or "Памятка", row["mime_type"] or ""),
            )
        conn.commit()


def get_projects():
    with get_connection() as conn:
        return conn.execute(
            "SELECT id,name,file_id,file_name,mime_type FROM knowledge_projects ORDER BY name COLLATE NOCASE"
        ).fetchall()


def get_project(project_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id,name,file_id,file_name,mime_type FROM knowledge_projects WHERE id=?",
            (project_id,),
        ).fetchone()


def get_project_files(project_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id,project_id,file_id,file_name,mime_type FROM knowledge_files WHERE project_id=? ORDER BY id",
            (project_id,),
        ).fetchall()


def get_project_file_count(project_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_files WHERE project_id=?",
            (project_id,),
        ).fetchone()
        return int(row["count"] if row else 0)


def project_name_exists(name):
    with get_connection() as conn:
        return conn.execute("SELECT 1 FROM knowledge_projects WHERE name=?", (name,)).fetchone() is not None


def add_project(name, file_id=None, file_name=None, mime_type=None):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_projects(name,file_id,file_name,mime_type,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
            (name, file_id, file_name, mime_type),
        )
        project_id = cur.lastrowid
        if file_id:
            conn.execute(
                "INSERT INTO knowledge_files(project_id,file_id,file_name,mime_type) VALUES(?,?,?,?)",
                (project_id, file_id, file_name or "Памятка", mime_type or ""),
            )
        conn.commit()
        return project_id


def add_project_file(project_id, file_id, file_name, mime_type=None):
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM knowledge_files WHERE project_id=?", (project_id,)).fetchone()
        count = int(row["count"] if row else 0)
        if count >= MAX_FILES_PER_PROJECT:
            raise ValueError(f"В проекте уже максимум {MAX_FILES_PER_PROJECT} файлов.")
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_files(project_id,file_id,file_name,mime_type) VALUES(?,?,?,?)",
            (project_id, file_id, file_name or "Памятка", mime_type or ""),
        )
        conn.execute(
            "UPDATE knowledge_projects SET file_id=?,file_name=?,mime_type=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (file_id, file_name or "Памятка", mime_type or "", project_id),
        )
        conn.commit()


def delete_project_file(file_row_id):
    with get_connection() as conn:
        row = conn.execute("SELECT project_id FROM knowledge_files WHERE id=?", (file_row_id,)).fetchone()
        if not row:
            return
        project_id = row["project_id"]
        conn.execute("DELETE FROM knowledge_files WHERE id=?", (file_row_id,))
        first = conn.execute(
            "SELECT file_id,file_name,mime_type FROM knowledge_files WHERE project_id=? ORDER BY id LIMIT 1",
            (project_id,),
        ).fetchone()
        if first:
            conn.execute(
                "UPDATE knowledge_projects SET file_id=?,file_name=?,mime_type=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (first["file_id"], first["file_name"], first["mime_type"], project_id),
            )
        else:
            conn.execute(
                "UPDATE knowledge_projects SET file_id=NULL,file_name=NULL,mime_type=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (project_id,),
            )
        conn.commit()


def delete_project(project_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM knowledge_files WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM knowledge_projects WHERE id=?", (project_id,))
        conn.commit()


def build_cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True, one_time_keyboard=True)


def build_files_keyboard():
    return ReplyKeyboardMarkup([["✅ Готово"], ["❌ Отмена"]], resize_keyboard=True)


def build_user_projects_keyboard():
    rows = []
    for project in get_projects():
        count = get_project_file_count(project["id"])
        rows.append([InlineKeyboardButton(f"📄 {project['name']} ({count})", callback_data=f"kb_project:{project['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="kb_back")])
    return InlineKeyboardMarkup(rows)


def build_admin_projects_keyboard():
    rows = [[InlineKeyboardButton("➕ Добавить проект", callback_data="admin_kb_add")]]
    for project in get_projects():
        count = get_project_file_count(project["id"])
        rows.append([
            InlineKeyboardButton(f"✏️ {project['name']} ({count}/10)", callback_data=f"admin_kb_manage:{project['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"admin_kb_delete:{project['id']}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def build_project_manage_keyboard(project_id):
    rows = []
    for f in get_project_files(project_id):
        rows.append([InlineKeyboardButton(f"🗑 {f['file_name']}", callback_data=f"admin_kb_file_delete:{f['id']}")])
    if get_project_file_count(project_id) < MAX_FILES_PER_PROJECT:
        rows.append([InlineKeyboardButton("➕ Добавить файл", callback_data=f"admin_kb_add_file:{project_id}")])
    rows.append([InlineKeyboardButton("⬅️ К проектам", callback_data="admin_kb_list")])
    return InlineKeyboardMarkup(rows)


async def show_user_knowledge(update, edit=False):
    text = "📚 БАЗА ЗНАНИЙ\n\nВыбери проект, чтобы получить материалы:"
    markup = build_user_projects_keyboard()
    if edit:
        await update.edit_message_text(text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)


def start_add_session(admin_id):
    KB_SESSIONS[admin_id] = {"mode": "add_project", "project_id": None}


def start_add_file_session(admin_id, project_id):
    KB_SESSIONS[admin_id] = {"mode": "add_files", "project_id": project_id}


def finish_session(admin_id):
    KB_SESSIONS.pop(admin_id, None)


def get_session(admin_id):
    return KB_SESSIONS.get(admin_id)


async def show_admin_knowledge(query):
    projects = get_projects()
    text = "📚 БАЗА ЗНАНИЙ — АДМИН\n\n"
    if not projects:
        text += "Проектов пока нет.\n"
    else:
        for project in projects:
            text += f"• {project['name']} — {get_project_file_count(project['id'])}/{MAX_FILES_PER_PROJECT} файлов\n"
    text += "\nВ одном проекте можно хранить до 10 файлов."
    await query.edit_message_text(text, reply_markup=build_admin_projects_keyboard())


async def show_project_manage(query, project_id):
    project = get_project(project_id)
    if not project:
        await query.answer("Проект не найден.", show_alert=True)
        return
    files = get_project_files(project_id)
    text = f"📁 ПРОЕКТ: {project['name']}\n\nФайлов: {len(files)}/{MAX_FILES_PER_PROJECT}\n\n"
    for i, f in enumerate(files, 1):
        text += f"{i}. {f['file_name']}\n"
    await query.edit_message_text(text, reply_markup=build_project_manage_keyboard(project_id))


class KnowledgeTextFilter(filters.MessageFilter):
    def filter(self, message):
        if not message or not message.from_user:
            return False
        text = message.text or ""
        if text in {"📚 База знаний", "❌ Отмена", "✅ Готово"}:
            return True
        return message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None


class KnowledgeDocumentFilter(filters.MessageFilter):
    def filter(self, message):
        return bool(message and message.from_user and message.document and message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None)


async def handle_knowledge_text(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == "📚 База знаний":
        if user_id == ADMIN_ID:
            await update.message.reply_text("📚 Управление базой знаний:", reply_markup=build_admin_projects_keyboard())
        else:
            await show_user_knowledge(update)
        return

    if user_id != ADMIN_ID:
        return
    session = get_session(user_id)
    if not session:
        return

    if text == "❌ Отмена":
        finish_session(user_id)
        await update.message.reply_text("❌ Операция с базой знаний отменена.")
        return

    if text == "✅ Готово":
        project_id = session.get("project_id")
        if project_id:
            project = get_project(project_id)
            count = get_project_file_count(project_id)
            finish_session(user_id)
            await update.message.reply_text(f"✅ ГОТОВО\n\n📁 {project['name']}\n📎 Файлов: {count}/{MAX_FILES_PER_PROJECT}")
        return

    if session.get("mode") == "add_project":
        if not text:
            await update.message.reply_text("❌ Название проекта не может быть пустым.")
            return
        if project_name_exists(text):
            await update.message.reply_text("⚠️ Такой проект уже существует. Открой его в базе знаний и добавь файлы туда.")
            return
        project_id = add_project(text)
        session["project_id"] = project_id
        session["mode"] = "add_files"
        await update.message.reply_text(
            f"✅ Проект «{text}» создан.\n\n📎 Отправляй файлы по одному. Можно добавить до {MAX_FILES_PER_PROJECT} файлов.\n\nКогда закончишь — нажми «✅ Готово».",
            reply_markup=build_files_keyboard(),
        )


async def handle_knowledge_document(update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    session = get_session(admin_id)
    if not session or not session.get("project_id"):
        return
    document = update.message.document
    file_name = document.file_name or "Памятка"
    mime_type = document.mime_type or ""
    try:
        add_project_file(session["project_id"], document.file_id, file_name, mime_type)
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return
    project = get_project(session["project_id"])
    count = get_project_file_count(session["project_id"])
    if count >= MAX_FILES_PER_PROJECT:
        finish_session(admin_id)
        await update.message.reply_text(f"✅ Файл добавлен: {file_name}\n\n📁 {project['name']}\n📎 Файлов: {count}/{MAX_FILES_PER_PROJECT}\n\nЛимит проекта достигнут.")
        return
    await update.message.reply_text(
        f"✅ Файл добавлен: {file_name}\n\n📁 {project['name']}\n📎 Файлов: {count}/{MAX_FILES_PER_PROJECT}\n\nОтправь следующий файл или нажми «✅ Готово».",
        reply_markup=build_files_keyboard(),
    )


async def handle_knowledge_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data or ""

    if data == "kb_back":
        await query.edit_message_text("Раздел закрыт.")
        return

    if data.startswith("kb_project:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        project = get_project(project_id)
        if not project:
            await query.answer("Проект не найден.", show_alert=True)
            return
        files = get_project_files(project_id)
        if not files:
            await query.answer("В проекте пока нет файлов.", show_alert=True)
            return
        for f in files:
            await context.bot.send_document(chat_id=user_id, document=f["file_id"], caption=f"📚 {project['name']}\n📎 {f['file_name']}")
        return

    if user_id != ADMIN_ID:
        await query.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    if data == "admin_kb_add":
        start_add_session(ADMIN_ID)
        await query.message.reply_text("➕ ДОБАВЛЕНИЕ ПРОЕКТА\n\nНапиши название проекта.\nНапример: МТС Банк\n\nПосле этого можно будет загрузить до 10 файлов.", reply_markup=build_cancel_keyboard())
        return

    if data.startswith("admin_kb_manage:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        await show_project_manage(query, project_id)
        return

    if data.startswith("admin_kb_add_file:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        if not get_project(project_id):
            await query.answer("Проект не найден.", show_alert=True)
            return
        if get_project_file_count(project_id) >= MAX_FILES_PER_PROJECT:
            await query.answer("У проекта уже 10 файлов.", show_alert=True)
            return
        start_add_file_session(ADMIN_ID, project_id)
        project = get_project(project_id)
        await query.message.reply_text(
            f"📎 ДОБАВЛЕНИЕ ФАЙЛОВ\n\nПроект: {project['name']}\nСейчас файлов: {get_project_file_count(project_id)}/{MAX_FILES_PER_PROJECT}\n\nОтправляй файлы по одному. Когда закончишь — нажми «✅ Готово».",
            reply_markup=build_files_keyboard(),
        )
        return

    if data.startswith("admin_kb_file_delete:"):
        try:
            file_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        with get_connection() as conn:
            row = conn.execute("SELECT project_id FROM knowledge_files WHERE id=?", (file_id,)).fetchone()
        if not row:
            await query.answer("Файл уже удалён.", show_alert=True)
            return
        delete_project_file(file_id)
        await show_project_manage(query, row["project_id"])
        return

    if data.startswith("admin_kb_delete:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        project = get_project(project_id)
        if not project:
            await query.answer("Проект уже удалён.", show_alert=True)
            return
        await query.edit_message_text(
            f"🗑 УДАЛЕНИЕ ПРОЕКТА\n\n📁 {project['name']}\n\nУдалить проект вместе со всеми файлами?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Удалить", callback_data=f"admin_kb_confirm_delete:{project_id}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="admin_kb_list")],
            ]),
        )
        return

    if data == "admin_kb_list":
        await show_admin_knowledge(query)
        return

    if data.startswith("admin_kb_confirm_delete:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        delete_project(project_id)
        await query.edit_message_text("✅ Проект удалён.", reply_markup=build_admin_projects_keyboard())


def install(bot_module):
    init_knowledge_db()
    from telegram import ReplyKeyboardMarkup
    bot_module.USER_MENU = ReplyKeyboardMarkup(
        [["💰 Заработок", "📅 Сегодня"], ["📆 Неделя", "🗓 Месяц"], ["📥 Загрузить заявки", "📥 Последние заявки"], ["📚 База знаний"], ["⚙️ Настройки"]],
        resize_keyboard=True,
    )
    bot_module.ADMIN_MENU = ReplyKeyboardMarkup(
        [["💰 Заработок", "📅 Сегодня"], ["📆 Неделя", "🗓 Месяц"], ["📥 Загрузить заявки", "📥 Последние заявки"], ["📚 База знаний"], ["⚙️ Настройки"], ["🛠 Админ-панель"]],
        resize_keyboard=True,
    )
    bot_module.ADMIN_PANEL_MENU = ReplyKeyboardMarkup(
        [["👥 Пользователи"], ["📊 Общая статистика"], ["📋 Все заявки"], ["⚙️ Тарифы"], ["🔄 Пересчитать заявки"], ["🔧 Технический режим"], ["📚 База знаний"], ["💸 Корректировка"], ["📢 Рассылка"], ["⬅️ Назад"]],
        resize_keyboard=True,
    )
    from telegram.ext import Application
    original_add_handler = Application.add_handler
    installed_apps = set()
    def patched_add_handler(self, handler, group=0):
        app_id = id(self)
        if app_id not in installed_apps:
            original_add_handler(self, CallbackQueryHandler(handle_knowledge_callback, pattern=r"^(kb_|admin_kb_)"), group=-1)
            original_add_handler(self, MessageHandler(KnowledgeDocumentFilter(), handle_knowledge_document), group=-1)
            original_add_handler(self, MessageHandler(KnowledgeTextFilter(), handle_knowledge_text), group=-1)
            installed_apps.add(app_id)
        return original_add_handler(self, handler, group)
    Application.add_handler = patched_add_handler
