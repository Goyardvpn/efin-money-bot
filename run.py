"""Точка входа бота (Amvera запускает именно этот файл, см. amvera.yaml).

Порядок подключения модулей важен: каждый install() оборачивает
обработчики из bot.py, поэтому менять последовательность не нужно.
"""

import bot
import knowledge
import knowledge_texts_ai
import knowledge_bootstrap
import ai_feature
import ui_router
import github_knowledge
import daily_digest


def main():
    # База знаний (SQLite) и её интерфейс.
    knowledge.init_knowledge_db()
    knowledge_bootstrap.install(bot)
    knowledge_texts_ai.install()

    # Efin AI получает знания напрямую из GitHub-репозитория
    # Goyardvpn/efin-knowledge-base, а не из Telegram-БД.
    # Подмена источника должна произойти до ai_feature.install().
    ai_feature.ask_efin_ai = github_knowledge.ask_efin_ai
    ai_feature.install(bot)

    # Навигация и меню.
    ui_router.install(bot)

    # Утренняя рассылка 07:00 МСК (погода в Москве + цитата), команда /digest для админа.
    daily_digest.install()

    bot.main()


if __name__ == "__main__":
    main()
