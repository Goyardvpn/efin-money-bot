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
| `daily_digest.py` | рассылка в 07:00 МСК: погода в Москве и цитата; `/digest` — отправить админу сейчас |

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

## Разработка и Claude Code

```bash
pip install -r requirements-dev.txt   # pytest и ruff
python -m pytest                      # тесты разбора заявок, периодов выплат и заработка
ruff check .                          # поиск настоящих ошибок (ruff.toml)
```

Для работы в Claude Code в репозитории есть:

| Файл | Назначение |
| --- | --- |
| `CLAUDE.md` | краткое описание проекта, команды и правила |
| `.claude/skills/project-conventions` | бизнес-правила: тарифы, статусы, периоды выплат, порядок подключения модулей |
| `.claude/skills/add-payable-status` | команда `/add-payable-status`: добавить оплачиваемый статус заявки |
| `.claude/agents/` | субагенты `test-writer` и `security-reviewer` |
| `.claude/settings.json`, `.claude/hooks/` | хуки: защита `.env` и `data/*.db`, проверка Ruff после правки `.py` |
| `.mcp.json` | MCP-сервер context7 с актуальной документацией библиотек |

На Windows, если команда `python3` не находится, замените её на `python` в `.claude/settings.json`.
