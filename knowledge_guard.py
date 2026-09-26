"""Гарантирует, что активная сессия базы знаний перехватывает текст раньше парсера заявок."""

import bot
import knowledge


_installed = False
_original_handle_message = None


def install():
    global _installed, _original_handle_message

    if _installed:
        return

    _original_handle_message = bot.handle_message

    async def guarded_handle_message(update, context):
        user = update.effective_user
        message = update.message

        if (
            user
            and message
            and user.id == knowledge.ADMIN_ID
            and knowledge.get_session(user.id) is not None
        ):
            await knowledge.handle_knowledge_text(update, context)
            return

        await _original_handle_message(update, context)

    bot.handle_message = guarded_handle_message
    _installed = True
    print("[Efin KB] Guard активирован: сообщения в активной сессии базы знаний не попадут в parser.py")
