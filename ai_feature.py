from telegram import ReplyKeyboardMarkup

from ai_assistant import ask_efin_ai

AI_SESSIONS = set()


def _user_menu():
    return ReplyKeyboardMarkup(
        [
            ["💰 Заработок", "📅 Сегодня"],
            ["📆 Неделя", "🗓 Месяц"],
            ["📥 Загрузить заявки", "📥 Последние заявки"],
            ["🤖 Efin AI", "📚 База знаний"],
            ["⚙️ Настройки"],
        ],
        resize_keyboard=True,
    )


def _admin_menu():
    return ReplyKeyboardMarkup(
        [
            ["💰 Заработок", "📅 Сегодня"],
            ["📆 Неделя", "🗓 Месяц"],
            ["📥 Загрузить заявки", "📥 Последние заявки"],
            ["🤖 Efin AI", "📚 База знаний"],
            ["⚙️ Настройки"],
            ["🛠 Админ-панель"],
        ],
        resize_keyboard=True,
    )


async def _handle(update, context, original_handler, bot_module):
    if not update.message or not update.message.text:
        return await original_handler(update, context)

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "🤖 Efin AI":
        AI_SESSIONS.add(user_id)
        await update.message.reply_text(
            "🤖 EFIN AI\n\n"
            "Я подключён к базе знаний EFIN.\n"
            "Задай вопрос по проектам, памяткам, картам, выплатам или инструкциям.\n\n"
            "Если информации нет в базе, я скажу об этом и не буду придумывать ответ.\n\n"
            "Для выхода нажми «⬅️ Назад»."
        )
        return

    if user_id not in AI_SESSIONS:
        return await original_handler(update, context)

    if text == "⬅️ Назад":
        AI_SESSIONS.discard(user_id)
        await update.message.reply_text(
            "Главное меню 👇",
            reply_markup=bot_module.get_menu(user_id),
        )
        return

    if len(text) > 12000:
        await update.message.reply_text("⚠️ Сообщение слишком длинное. Отправь вопрос короче.")
        return

    await update.message.chat.send_action("typing")
    try:
        answer = await ask_efin_ai(context.bot, text)
    except Exception as exc:
        print(f"[Efin AI] {type(exc).__name__}: {exc}")
        await update.message.reply_text(
            "⚠️ Efin AI не смог получить ответ.\n\n"
            "Попробуй ещё раз через несколько секунд."
        )
        return

    await update.message.reply_text(answer)


def install(bot_module):
    bot_module.USER_MENU = _user_menu()
    bot_module.ADMIN_MENU = _admin_menu()

    original_handler = bot_module.handle_message

    async def wrapped_handle_message(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if (
            user_id is not None
            and user_id != bot_module.ADMIN_ID
            and bot_module.get_maintenance_mode()
        ):
            return await original_handler(update, context)
        return await _handle(update, context, original_handler, bot_module)

    bot_module.handle_message = wrapped_handle_message
