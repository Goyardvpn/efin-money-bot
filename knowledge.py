from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, filters

from config import ADMIN_ID
from knowledge_db import get_connection

MAX_FILES_PER_PROJECT = 50
KB_SESSIONS = {}

KB_NAVIGATION_TEXTS = {
    "🤖 Efin AI",
    "👤 Личный кабинет",
    "🛠 Админ-панель",
    "⬅️ Выйти",
    "📚 База знаний",
}


def init_knowledge_db():
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            file_id TEXT,
            file_name TEXT,
            mime_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            mime_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, file_id),
            FOREIGN KEY(project_id) REFERENCES knowledge_projects(id) ON DELETE CASCADE
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES knowledge_projects(id) ON DELETE CASCADE
        )""")
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


def get_project_texts(project_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT id,project_id,text,created_at FROM knowledge_texts WHERE project_id=? ORDER BY id",
            (project_id,),
        ).fetchall()


def get_project_file_count(project_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_files WHERE project_id=?",
            (project_id,),
        ).fetchone()
        return int(row["count"] if row else 0)


def get_project_text_count(project_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_texts WHERE project_id=?",
            (project_id,),
        ).fetchone()
        return int(row["count"] if row else 0)


def add_project_text(project_id, text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Текст не может быть пустым.")
    with get_connection() as conn:
        conn.execute("INSERT INTO knowledge_texts(project_id,text) VALUES(?,?)", (project_id, text))
        conn.execute("UPDATE knowledge_projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
        conn.commit()


def delete_project_text(text_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM knowledge_texts WHERE id=?", (text_id,))
        conn.commit()


def project_name_exists(name):
    with get_connection() as conn:
        return conn.execute("SELECT 1 FROM knowledge_projects WHERE name=?", (name,)).fetchone() is not None


def add_project(name, file_id=None, file_name=None, mime_type=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Название проекта не может быть пустым.")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_projects(name,file_id,file_name,mime_type,updated_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",
            (name, file_id, file_name, mime_type),
        )
        project_id = cur.lastrowid
        if file_id:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_files(project_id,file_id,file_name,mime_type) VALUES(?,?,?,?)",
                (project_id, file_id, file_name or "Памятка", mime_type or ""),
            )
        conn.commit()
        return project_id


def add_project_file(project_id, file_id, file_name, mime_type=None):
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM knowledge_files WHERE project_id=?", (project_id,)).fetchone()
        count = int(row["count"] if row else 0)
        if count >= MAX_FILES_PER_PROJECT:
            raise ValueError(f"В проекте уже максимум {MAX_FILES_PER_PROJECT} файлов/фото.")
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
        conn.execute("DELETE FROM knowledge_texts WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM knowledge_files WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM knowledge_projects WHERE id=?", (project_id,))
        conn.commit()


def build_files_keyboard():
    return ReplyKeyboardMarkup([["✅ Готово"], ["❌ Отмена"]], resize_keyboard=True)


def build_user_projects_keyboard():
    rows = []
    for project in get_projects():
        files = get_project_file_count(project["id"])
        texts = get_project_text_count(project["id"])
        rows.append([InlineKeyboardButton(f"📄 {project['name']} ({files + texts})", callback_data=f"kb_project:{project['id']}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="kb_back")])
    return InlineKeyboardMarkup(rows)


def build_admin_projects_keyboard():
    rows = [[InlineKeyboardButton("➕ Добавить проект", callback_data="admin_kb_add")]]
    for project in get_projects():
        files = get_project_file_count(project["id"])
        texts = get_project_text_count(project["id"])
        rows.append([
            InlineKeyboardButton(f"✏️ {project['name']} ({files}ф/{texts}т)", callback_data=f"admin_kb_manage:{project['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"admin_kb_delete:{project['id']}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def build_project_manage_keyboard(project_id):
    rows = []
    for f in get_project_files(project_id):
        rows.append([InlineKeyboardButton(f"🗑 📎 {f['file_name']}", callback_data=f"admin_kb_file_delete:{f['id']}")])
    for t in get_project_texts(project_id):
        preview = " ".join(t["text"].split())[:55]
        rows.append([InlineKeyboardButton(f"🗑 📝 {preview}", callback_data=f"admin_kb_text_delete:{t['id']}")])
    if get_project_file_count(project_id) < MAX_FILES_PER_PROJECT:
        rows.append([InlineKeyboardButton("➕ Добавить файл или текст", callback_data=f"admin_kb_add_file:{project_id}")])
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
    KB_SESSIONS[admin_id] = {"mode": "add_materials", "project_id": project_id}


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
            files = get_project_file_count(project["id"])
            texts = get_project_text_count(project["id"])
            text += f"• {project['name']} — {files}/{MAX_FILES_PER_PROJECT} файлов + {texts} текстов\n"
    text += "\nМожно добавлять PDF, DOCX, PPTX, TXT, фото и обычный текст."
    await query.edit_message_text(text, reply_markup=build_admin_projects_keyboard())


async def show_project_manage(query, project_id):
    project = get_project(project_id)
    if not project:
        await query.answer("Проект не найден.", show_alert=True)
        return
    files = get_project_files(project_id)
    texts = get_project_texts(project_id)
    text = (
        f"📁 ПРОЕКТ: {project['name']}\n\n"
        f"📎 Файлов/фото: {len(files)}/{MAX_FILES_PER_PROJECT}\n"
        f"📝 Текстовых материалов: {len(texts)}\n\n"
    )
    for i, f in enumerate(files, 1):
        text += f"📎 {i}. {f['file_name']}\n"
    for i, t in enumerate(texts, 1):
        text += f"📝 {i}. {' '.join(t['text'].split())[:100]}\n"
    await query.edit_message_text(text, reply_markup=build_project_manage_keyboard(project_id))


class KnowledgeTextFilter(filters.MessageFilter):
    def filter(self, message):
        if not message or not message.from_user:
            return False
        text = (message.text or "").strip()
        if text in KB_NAVIGATION_TEXTS:
            return False
        if text in {"❌ Отмена", "✅ Готово"}:
            return True
        return message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None


class KnowledgeDocumentFilter(filters.MessageFilter):
    def filter(self, message):
        return bool(message and message.from_user and message.document and message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None)


async def handle_knowledge_text(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
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
            files = get_project_file_count(project_id)
            texts = get_project_text_count(project_id)
            finish_session(user_id)
            await update.message.reply_text(
                f"✅ ГОТОВО\n\n📁 {project['name']}\n"
                f"📎 Файлов/фото: {files}/{MAX_FILES_PER_PROJECT}\n"
                f"📝 Текстов: {texts}"
            )
        return

    if session.get("mode") == "add_project":
        if not text:
            await update.message.reply_text("❌ Название проекта не может быть пустым.")
            return
        if project_name_exists(text):
            await update.message.reply_text("❌ Такой проект уже существует. Введи другое название.")
            return
        project_id = add_project(text)
        start_add_file_session(user_id, project_id)
        await update.message.reply_text(
            f"✅ Проект «{text}» создан.\n\n"
            "Теперь присылай файлы/фото или текстовые материалы.\n"
            f"Можно добавить до {MAX_FILES_PER_PROJECT} файлов/фото.\n\n"
            "Когда закончишь — нажми «✅ Готово». ",
            reply_markup=build_files_keyboard(),
        )
        return

    if session.get("mode") == "add_materials":
        project_id = session.get("project_id")
        if not project_id:
            finish_session(user_id)
            return
        if text:
            add_project_text(project_id, text)
            await update.message.reply_text("📝 Текст добавлен.")


async def handle_knowledge_document(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.message.document:
        return
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    session = get_session(user_id)
    if not session or session.get("mode") != "add_materials":
        return
    project_id = session.get("project_id")
    if not project_id:
        finish_session(user_id)
        return
    document = update.message.document
    if get_project_file_count(project_id) >= MAX_FILES_PER_PROJECT:
        await update.message.reply_text(f"❌ Достигнут лимит {MAX_FILES_PER_PROJECT} файлов/фото.")
        return
    add_project_file(project_id, document.file_id, document.file_name or "Файл", document.mime_type or "")
    await update.message.reply_text(f"📎 Файл добавлен: {document.file_name or 'Файл'}")


async def handle_knowledge_photo(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.message.photo:
        return
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    session = get_session(user_id)
    if not session or session.get("mode") != "add_materials":
        return
    project_id = session.get("project_id")
    if not project_id:
        finish_session(user_id)
        return
    if get_project_file_count(project_id) >= MAX_FILES_PER_PROJECT:
        await update.message.reply_text(f"❌ Достигнут лимит {MAX_FILES_PER_PROJECT} файлов/фото.")
        return
    photo = update.message.photo[-1]
    add_project_file(project_id, photo.file_id, "Фото.jpg", "image/jpeg")
    await update.message.reply_text("🖼 Фото добавлено.")


async def handle_knowledge_callback(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    user_id = query.from_user.id

    if data == "kb_back":
        await show_user_knowledge(query, edit=True)
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
        texts = get_project_texts(project_id)
        await query.edit_message_text(
            f"📁 {project['name']}\n\n"
            f"Файлов/фото: {len(files)}\n"
            f"Текстов: {len(texts)}\n\n"
            "Материалы проекта используются Efin AI при ответах."
        )
        return

    if user_id != ADMIN_ID:
        return

    if data == "admin_kb_list":
        finish_session(user_id)
        await show_admin_knowledge(query)
        return

    if data == "admin_kb_add":
        start_add_session(user_id)
        await query.edit_message_text(
            "➕ Введи название нового проекта:",
        )
        return

    if data.startswith("admin_kb_manage:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        finish_session(user_id)
        await show_project_manage(query, project_id)
        return

    if data.startswith("admin_kb_add_file:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        start_add_file_session(user_id, project_id)
        project = get_project(project_id)
        if not project:
            finish_session(user_id)
            await query.answer("Проект не найден.", show_alert=True)
            return
        await query.edit_message_text(
            f"📎 Добавление материалов в «{project['name']}».\n\n"
            "Присылай PDF, DOCX, PPTX, TXT, изображения или обычный текст.\n"
            f"Лимит файлов/фото: {MAX_FILES_PER_PROJECT}.\n\n"
            "После загрузки нажми «✅ Готово»."
        )
        return

    if data.startswith("admin_kb_file_delete:"):
        try:
            row_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        delete_project_file(row_id)
        await query.edit_message_reply_markup(reply_markup=build_project_manage_keyboard(get_project_files(row_id)[0]['project_id']) if False else None)
        await show_admin_knowledge(query)
        return

    if data.startswith("admin_kb_text_delete:"):
        try:
            text_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        delete_project_text(text_id)
        await show_admin_knowledge(query)
        return

    if data.startswith("admin_kb_delete:"):
        try:
            project_id = int(data.split(":", 1)[1])
        except ValueError:
            return
        delete_project(project_id)
        finish_session(user_id)
        await show_admin_knowledge(query)
        return


# Регистрация обработчиков

