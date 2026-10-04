# efin-money-bot

Telegram-бот компании EFIN: личный кабинет (заявки, заработок, тарифы),
админ-панель и помощник **Efin AI**, который отвечает по базе знаний из
GitHub-репозитория.

## Структура

| Файл | Назначение |
| --- | --- |
| `run.py` | точка входа, подключает все модули |
| `bot.py` | основная логика: команды, кнопки, личный кабинет, админ-панель |
| `database.py` | SQLite: `users`, `earnings`, `tariffs`, `bot_settings` |
| `parser.py`, `rates.py` | разбор данных и курсы |
| `ui_router.py` | меню и навигация |
| `ai_feature.py`, `ai_assistant.py` | кнопка «🤖 Efin AI», запросы к TokenBoom API |
| `github_knowledge.py` | загрузка базы знаний из GitHub |
| `knowledge*.py` | управление базой знаний из Telegram |

## Запуск локально

```bash
pip install -r requirements.txt
cp .env.example .env   # и заполните значения
python run.py
```

Переменные окружения описаны в `.env.example`.

## Деплой на Amvera

Настройки лежат в `amvera.yaml`. Базы SQLite (`efin.db`, `knowledge.db`)
хранятся в постоянном хранилище `/data`; загрузите их туда вручную.
Папка `data/` в репозитории нужна только для файлов деплоя.
