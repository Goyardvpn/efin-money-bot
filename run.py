import bot
import knowledge
import ai_feature
import ui_router


knowledge.install(bot)
ai_feature.install(bot)
ui_router.install(bot)


bot.main()
