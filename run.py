import bot
import knowledge
import knowledge_texts_ai
import knowledge_bootstrap
import ai_feature
import ui_router
import github_knowledge


# Инициализация старой Telegram-БД и интерфейса.
# Efin AI теперь получает знания напрямую из GitHub-репозитория
# Goyardvpn/efin-knowledge-base, а не из Telegram-БД.
knowledge.init_knowledge_db()
knowledge_bootstrap.install(bot)
knowledge_texts_ai.install()

# Подменяем источник AI до установки обработчика.
ai_feature.ask_efin_ai = github_knowledge.ask_efin_ai
ai_feature.install(bot)
ui_router.install(bot)

bot.main()
