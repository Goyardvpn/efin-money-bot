import bot
import knowledge
import knowledge_media_handler
import knowledge_texts_ai
import ai_feature
import ui_router


knowledge.install(bot)
knowledge_media_handler.install(bot)
knowledge_texts_ai.install()
ai_feature.install(bot)
ui_router.install(bot)


bot.main()
