from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

from config import ADMIN_ID
from database import get_connection

MAX_FILES_PER_PROJECT = 50
KB_SESSIONS = {}

# Навигационные кнопки никогда не должны попадать в базу знаний.
# Иначе, если администратор ушёл из БЗ без «Готово», старая сессия
# продолжает перехватывать Efin AI / Личный кабинет / Выход.
KB_NAVIGATION_TEXTS = {
    "🤖 Efin AI",
    "👤 Личный кабинет",
    "🛠 Админ-панель",
    "⬅️ Выйти",
    "📚 База знаний",
}


def _column_info(conn, table):
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _migrate_projects_table(conn):
    """Мигрирует старую таблицу, где file_id был NOT NULL."""
    columns = _column_info(conn, "knowledge_projects")
    if not columns:
        return

    file_id_col = next((c for c in columns if c["name"] == "file_id"), None)
    if file_id_col is None or int(file_id_col["notnull"]) == 0:
        return

    conn.execute("ALTER TABLE knowledge_projects RENAME TO knowledge_projects_old")
    conn.execute("""CREATE TABLE knowledge_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        file_id TEXT,
        file_name TEXT,
        mime_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""INSERT INTO knowledge_projects
        (id,name,file_id,file_name,mime_type,created_at,updated_at)
        SELECT id,name,file_id,file_name,mime_type,created_at,updated_at
        FROM knowledge_projects_old""")
    conn.execute("DROP TABLE knowledge_projects_old")


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
        _migrate_projects_table(conn)

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

        old = conn.execute(
            "SELECT id,file_id,file_name,mime_type FROM knowledge_projects WHERE file_id IS NOT NULL"
        ).fetchall()
        for row in old:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_files(project_id,file_id,file_name,mime_type) VALUES(?,?,?,?)",
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
        conn.execute(
            "INSERT INTO knowledge_texts(project_id,text) VALUES(?,?)",
            (project_id, text),
        )
        conn.execute(
            "UPDATE knowledge_projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (project_id,),
        )
        conn.commit()


def delete_project_text(text_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM knowledge_texts WHERE id=?", (text_id,))
        conn.commit()


def project_name_exists(name):
    with get_connection() as conn:
        return conn.execute(
            "SELECT 1 FROM knowledge_projects WHERE name=?",
            (name,),
        ).fetchone() is not None


def add_project(name, file_id=None, file_name=None, mime_type=None):
    """Создаёт проект без обязательного файла."""
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
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_files WHERE project_id=?",
            (project_id,),
        ).fetchone()
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
        row = conn.execute(
            "SELECT project_id FROM knowledge_files WHERE id=?",
            (file_row_id,),
        ).fetchone()
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


def build_cancel_keyboard():
    return ReplyKeyboardMarkup(
        [["❌ Отмена"]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_files_keyboard():
    return ReplyKeyboardMarkup(
        [["✅ Готово"], ["❌ Отмена"]],
        resize_keyboard=True,
    )


def build_user_projects_keyboard():
    rows = []
    for project in get_projects():
        files = get_project_file_count(project["id"])
        texts = get_project_text_count(project["id"])
        rows.append([
            InlineKeyboardButton(
                f"📄 {project['name']} ({files + texts})",
                callback_data=f"kb_project:{project['id']}",
            )
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="kb_back")])
    return InlineKeyboardMarkup(rows)


def build_admin_projects_keyboard():
    rows = [[InlineKeyboardButton("➕ Добавить проект", callback_data="admin_kb_add")]]
    for project in get_projects():
        files = get_project_file_count(project["id"])
        texts = get_project_text_count(project["id"])
        rows.append([
            InlineKeyboardButton(
                f"✏️ {project['name']} ({files}ф/{texts}т)",
                callback_data=f"admin_kb_manage:{project['id']}",
            ),
            InlineKeyboardButton(
                "🗑",
                callback_data=f"admin_kb_delete:{project['id']}",
            ),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def build_project_manage_keyboard(project_id):
    rows = []
    for f in get_project_files(project_id):
        rows.append([
            InlineKeyboardButton(
                f"🗑 📎 {f['file_name']}",
                callback_data=f"admin_kb_file_delete:{f['id']}",
            )
        ])
    for t in get_project_texts(project_id):
        preview = " ".join(t["text"].split())[:55]
        rows.append([
            InlineKeyboardButton(
                f"🗑 📝 {preview}",
                callback_data=f"admin_kb_text_delete:{t['id']}",
            )
        ])
    if get_project_file_count(project_id) < MAX_FILES_PER_PROJECT:
        rows.append([
            InlineKeyboardButton(
                "➕ Добавить файл или текст",
                callback_data=f"admin_kb_add_file:{project_id}",
            )
        ])
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
        preview = " ".join(t["text"].split())[:100]
        text += f"📝 {i}. {preview}\n"

    await query.edit_message_text(
        text,
        reply_markup=build_project_manage_keyboard(project_id),
    )


class KnowledgeTextFilter(filters.MessageFilter):
    def filter(self, message):
        if not message or not message.from_user:
            return False
        text = (message.text or "").strip()

        # Навигация должна обрабатываться ui_router / ai_feature, а не БЗ.
        if text in KB_NAVIGATION_TEXTS:
            return False

        if text in {"📚 База знаний", "❌ Отмена", "✅ Готово"}:
            return True
        return message.from_user.id == ADMIN_ID and get_session(ADMIN_ID) is not None


class KnowledgeDocumentFilter(filters.MessageFilter):
    def filter(self, message):
        return bool(
            message
            and message.from_user
            and message.document
            and message.from_user.id == ADMIN_ID
            and get_session(ADMIN_ID) is not None
        )


async def handle_knowledge_text(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == "📚 База знаний":
        if user_id == ADMIN_ID:
            await update.message.reply_text(
                "📚 Управление базой знаний:",
                reply_markup=build_admin_projects_keyboard(),
            )
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
            await update.message.reply_text(
                "⚠️ Такой проект уже существует. Открой его в базе знаний и добавь материалы туда."
            )
            return

        project_id = add_project(text)
        session["project_id"] = project_id
        session["mode"] = "add_materials"

        await update.message.reply_text(
            f"✅ Проект «{text}» создан.\n\n"
            "📎 Теперь просто отправляй сюда файлы, фото ИЛИ обычный текст из группы стажёров.\n\n"
            "Когда закончишь — нажми «✅ Готово».",
            reply_markup=build_files_keyboard(),
        )
        return

    if session.get("mode") == "add_materials":
        project_id = session.get("project_id")
        if not project_id or not text:
            return

        try:
            add_project_text(project_id, text)
        except ValueError as exc:
            await update.message.reply_text(f"⚠️ {exc}")
            return

        project = get_project(project_id)
        count = get_project_text_count(project_id)
        await update.message.reply_text(
            f"✅ Текст добавлен в базу\n\n"
            f"📁 {project['name']}\n"
            f"📝 Текстовых материалов: {count}\n\n"
            "Можно отправить следующий текст, файл или фото.",
            reply_markup=build_files_keyboard(),
        )


async def handle_knowledge_document(update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
