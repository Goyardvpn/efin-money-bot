import bot
import knowledge
import knowledge_texts_ai
import knowledge_bootstrap
import ai_feature
import ui_router


# Инициализация базы знаний и её прямое подключение к Application.
# Старые monkey-patch модули knowledge_guard/knowledge_media_handler
# здесь больше не используются: bootstrap регистрирует обработчики
# непосредственно перед запуском polling.
knowledge.init_knowledge_db()
knowledge_bootstrap.install(bot)
knowledge_texts_ai.install()
ai_feature.install(bot)
ui_router.install(bot)


bot.main()
