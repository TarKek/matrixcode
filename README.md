# matrixcode

локальный ai-ассистент для программирования. работает с `llama-server` через
openai-совместимый api, управляется из текстового tui, вызывает инструменты
(файлы, shell, поиск, интернет, чекпоинты), ведёт план задач, держит
долговременную память и переживает перезапуск через `--continue`.

## быстрый старт

1. поднять сервер модели (llama-server с openai-совместимым endpoint на
   `http://127.0.0.1:8080/v1`).
2. запустить ui:

```powershell
python main.py                # новая сессия
python main.py --continue     # продолжить последнюю
python main.py --dev          # профиль approval dev
python main.py --policy safe  # профиль safe
```

зависимости: `textual>=0.60`, `httpx>=0.27`, `rich` (идёт с textual).
опционально: `matplotlib` + `Pillow` для `show_image`, `tomllib` (stdlib 3.11+)
для разбора `pyproject` в `project_info`.

> примечание: файл `start_server.py` в репозитории отсутствует  остался
> только ярлык `start_server.py  ярлык.lnk`. сервер поднимается вручную
> или отдельным скриптом вне этого каталога.

## философия: всё  модуль

matrixcode собран из независимых модулей. никакого одного большого main.py
и никакого реестра, который надо править руками при добавлении фичи.

- **хочешь новый тул?** кинь `.py` в `tools/`, добавь `register(reg)` 
  подхватится при следующем старте.
- **хочешь новый скилл?** то же самое, только в `skills/`.
- **хочешь свою слэш-команду?** то же самое, только в `commands/`.

ничего нигде не регистрируется вручную. `_iter_modules` в `core/registries.py`
обходит папку, импортирует всё, что не начинается с `_`, и вызывает
`register()`. если модуль падает  в stdout уйдёт traceback, и ты увидишь
это в логе старта.

## структура

```text
matrixcode/
 main.py                  точка входа: собрать всё и запустить tui
 README.md                этот файл
 requirements.txt         textual, httpx

 core/                    базовые утилиты, ни от кого не зависят
    paths.py             пути, env-переменные, все константы
    logger.py            запись событий в logs/session-*.jsonl
    sandbox.py           ограничение файловых операций workspace'ом
    childsandbox/
       sitecustomize.py автопатч дочерних python через PYTHONPATH
    registries.py        реестры тулов / скиллов / команд + загрузка
    parser.py            разбор <call- ... -call>, fingerprint'ы
    display.py           очистка текста, brief-строки для ui
    messages.py          склейка сообщений, is_tool_result
    compression.py       сжатие старых tool-result'ов в контексте
    summarize.py         семантическое резюме старой части истории
    policy.py            профили approval (strict/normal/dev/safe)
    verify.py            post-check файлов после write/edit (py_compile)

 llm/
    client.py            streaming chat-completions, /props, /models

 execution/
    executor.py          вызов одного тула + обработка ошибок

 agent/                   мозг: цикл диалога с моделью
    agent.py             класс Agent (главный цикл)
    loop_guard.py        сообщения-коррекции при зацикливании
    context.py           workspace-снимок, MEMORY.md в промпт
    prompts.py           загрузка системного промпта

 ui/                      tui (textual)
    app.py               MatrixCodeApp, CSS, ввод, /команды
    chat.py              левая панель: чат + инлайн-строки тулов
    stats.py             правая панель + нижний статус-бар
    markup.py            безопасный разбор rich-разметки
    callbacks.py         класс CB: связка Agent  виджеты

 tools/                   инструменты, каждый  отдельный .py
    checkpoint.py        checkpoint / checkpoint_list / checkpoint_revert
    delete_file.py
    edit_file.py
    fetch_url.py         GET по url, html  текст (approval)
    find_files.py
    grep_files.py
    list_dir.py
    open_file.py         open в системном вьювере (whitelist ext)
    project_info.py      one-shot разведка проекта
    read_file.py
    rename_file.py
    run_shell.py         shell + classifier + child sandbox
    show_image.py        рендер png в ansi-полублоки
    todo.py              todo_write / todo_read  план между итерациями
    write_file.py

 skills/                  промпт-уровневые скиллы
    format_text.py
    planning.py
    verification.py

 commands/                слэш-команды tui
    approvals.py         /approvals
    audit.py             /audit
    compact.py           /compact
    continue.py          /continue, /cont
    help.py              /help
    iters.py             /iters
    policy.py            /policy
    summarize.py         /summarize, /sum

 prompts/                 system.md, tools.gbnf
 logs/                    session-*.jsonl
 tests/                   unit-тесты, run_all.py
 workspace/               песочница агента
     MEMORY.md            долговременная память (опционально)
     .matrixcode/         служебное: todos.json
     .checkpoints/        сохранённые снапшоты workspace
```

## тулы

полный список того, что модель видит в промпте:

| тул | назначение |
|---|---|
| `read_file` | прочитать текстовый файл из workspace |
| `write_file` | записать файл целиком (с post-check) |
| `edit_file` | заменить один уникальный фрагмент |
| `delete_file` | удалить файл |
| `rename_file` | переместить / переименовать |
| `list_dir` | содержимое папки |
| `find_files` | glob-поиск файлов |
| `grep_files` | regex-поиск по содержимому |
| `project_info` | one-shot разведка: стек, зависимости, entrypoints |
| `run_shell` | shell-команда + classifier + sandbox |
| `fetch_url` | GET по url, html  текст (approval) |
| `show_image` | рендер png/jpg в ansi-полублоки |
| `open_file` | открыть файл дефолтным приложением (whitelist ext) |
| `todo_write` | записать план (todos.json) |
| `todo_read` | прочитать план |
| `checkpoint` | снять снапшот workspace |
| `checkpoint_list` | список снапшотов |
| `checkpoint_revert` | откатить workspace к снапшоту |

## слэш-команды

| команда | что делает |
|---|---|
| `/help` | список команд и подсказки |
| `/continue` (`/cont`) | продолжить ход ассистента без нового user-сообщения |
| `/compact` | сжать историю прямо сейчас |
| `/summarize` (`/sum`) | семантически сжать старую часть истории |
| `/iters` | сколько tool-итераций потрачено |
| `/policy` | показать / сменить профиль approval |
| `/approvals` | список активных разрешений на пути |
| `/audit` | сводка событий из logs/session-*.jsonl |

## как добавить тул, скилл, команду

### тул

`tools/my_tool.py`:

```python
def _run(text: str) -> str:
    return f"ok: {text.upper()}"

def register(reg):
    reg.add(
        "my_tool",
        '<call- my_tool: text:"hi" -call>\n'
        "uppercases text.\n"
        "Args: text (string, required).\n"
        "Result: <result>ok: HI</result>",
        _run,
    )
```

перезапусти `main.py`  тул появится в промпте. никакой регистрации в других
файлах.

### скилл

`skills/my_skill.py`:

```python
DOC = """\
Use this skill when you need to X. Format your reply as Y.
"""
def register(reg):
    reg.add("my_skill", DOC)
```

### команда

`commands/my_cmd.py`:

```python
def _run(app, args: str) -> None:
    app.push_chat(f"you typed: {args}")

def register(reg):
    reg.add("my_cmd", "Does nothing in particular.", _run)
```

## куда лезть за чем

| хочу поменять | открыть файл |
|---|---|
| системный промпт | `prompts/system.md` |
| добавить новый тул | `tools/<имя>.py` (см. выше) |
| поведение тула | `tools/<имя>.py` |
| добавить скилл | `skills/<имя>.py` |
| добавить слэш-команду | `commands/<имя>.py` |
| форму tool-call | `core/parser.py` |
| текст в чате | `ui/chat.py` |
| правую панель | `ui/stats.py` |
| css / расположение | `ui/app.py`, константа `CSS` |
| реакцию на зацикливание | `agent/loop_guard.py` |
| главный цикл | `agent/agent.py`, метод `ask` |
| сжатие контекста | `core/compression.py` |
| семантическое резюме | `core/summarize.py` |
| sandbox | `core/sandbox.py` |
| child sandbox | `core/childsandbox/sitecustomize.py` |
| классификатор команд | `tools/run_shell.py`, `_SUSPICIOUS` |
| профили approval | `core/policy.py` |
| post-check файлов | `core/verify.py` |
| лимиты | `core/paths.py` |
| логи | `core/logger.py` |

## формат tool-call

ассистент эмитит вызовы как живой текст:

```text
<call- name: key:value key:value -call>
```

правила:

1. один вызов за ход. хост вернёт `<result>...</result>`, только тогда эмитить
   следующий.
2. короткие аргументы  `key:value`, значение в двойных кавычках.
3. длинные и многострочные  `key>...`, форма съедает всё до закрывающего
   тега. не экранируй `\"`, пиши сыро.
4. только одна `key>` форма за вызов, и она идёт последней.
5. не оборачивай вызовы в блоки кода  парсер считает такое кодом.

примеры:

```text
<call- list_dir: path:"." -call>

<call- run_shell: command:"dir" timeout:30 -call>

<call- write_file: path:"a.py" content>def foo():
    return 42</call>
```

для `edit_file`: `old` должен быть уникальной строкой. если встречается
несколько раз  добавь 23 строки контекста вокруг.

## env-переменные

все с префиксом `MATRIXCODE_`. дефолты  в `core/paths.py`.

### llm-соединение

| переменная | дефолт | что делает |
|---|---|---|
| `BASE_URL` | `http://127.0.0.1:8080/v1` | адрес llama-server |
| `MODEL` | `local-model` | имя модели |
| `API_KEY` | `sk-no-key` | bearer |
| `TIMEOUT` | `300` | секунды на один запрос к llm |

### генерация

| переменная | дефолт | что делает |
|---|---|---|
| `TEMPERATURE` | `0.4` | sampling при выключенном thinking |
| `THINKING_TEMPERATURE` | `1.0` | sampling при включённом thinking |
| `MAX_TOKENS` | `2048` | `max_tokens` на ответ |
| `THINKING_BUDGET` | `-1` | `-1` auto, `0` off, `>0` токенов |

### агент-цикл

| переменная | дефолт | что делает |
|---|---|---|
| `MAX_ITERS` | `-1` | лимит тул-итераций за ход (-1 = нет) |
| `MAX_TOOL_CHARS` | `8000` | обрезка tool-result'а |
| `FP_REPEAT_LIMIT` | `2` | порог fingerprint-детектора |
| `LOOP_REPEAT_LIMIT` | `5` | порог call+result детектора |
| `MAX_LOOP_RECOVERIES` | `3` | авто-восстановлений за ход |

### управление контекстом

| переменная | дефолт | что делает |
|---|---|---|
| `CONTEXT_WINDOW` | `16384` | fallback, если `/props` не ответил |
| `COMPRESS_AT` | `0.7` | доля ctx для запуска сжатия |
| `KEEP_TURNS` | `4` | сколько ходов не сжимать |
| `SUMMARY` | `1` | включить семантическое резюме |
| `SUMMARY_AT` | `0.55` | доля ctx для запуска резюме |
| `SUMMARY_KEEP` | `4` | сколько последних сообщений не трогать |
| `SUMMARY_MIN_MSGS` | `12` | минимум сообщений для резюме |

### файловая раскладка

| переменная | дефолт | что делает |
|---|---|---|
| `LOG_DIR` | `logs` | папка логов |
| `TOOLS_DIR` | `tools` | папка тулов |
| `SKILLS_DIR` | `skills` | папка скиллов |
| `COMMANDS_DIR` | `commands` | папка команд |
| `WORKSPACE` | `workspace` | песочница агента |
| `SYSTEM_FILE` | `prompts/system.md` | системный промпт |
| `MEMORY_FILE` | `prompts/memory.md` | долговременная память |
| `GRAMMAR_FILE` | `prompts/tools.gbnf` | грамматика tool-call |
| `GRAMMAR` | `1` | включить грамматику |

## профили approval

один переключатель через env `MATRIXCODE_POLICY` или cli-флаг:

| профиль | поведение |
|---|---|
| `strict` | read-only команды тоже требуют approval. для запуска чужого кода |
| `normal` | дефолт. read-only без вопроса, остальное  approval |
| `dev` | снят шум: del/move/ren/pipe/redirect/chaining разрешены. сеть, абсолютные пути, system cmdlet, lolbin, inline-код по-прежнему требуют подтверждения |
| `safe` | approval-хук всегда возвращает deny. для демонстраций и тестов |

cli:

```text
python main.py --safe
python main.py --strict
python main.py --dev
python main.py --policy normal
python main.py --policy=normal
```

профиль читается один раз при импорте. менять на лету  только `/policy`
(см. `commands/policy.py`), при этом кэш причин в `run_shell` сбрасывается.

## security model

**что защищено:**

- все файловые операции агента ограничены `workspace/`. всё, что вне  через
  approval-хук tui.
- классификатор команд (`tools/run_shell.py`, список `_SUSPICIOUS`) отправляет
  в approval команды с абсолютными путями, `cd ..`, `%VAR%`, `~`, curl/wget,
  альтернативными шеллами, lolbin'ами, `python -S/-I/-E`, `pushd`, `mklink`,
  `set`, `whoami`, `reg`, `schtasks`, `wmic`, `certutil` и ещё десятками
  паттернов.
- дочерние python-процессы сами патчат себя через `sitecustomize.py` на
  `PYTHONPATH`: блокируют `builtins.open`, `os.*`, `os.startfile`,
  `shutil.copy*`, `subprocess` с `shell=True` вне workspace.
- любой запуск `.py`-скрипта через `run_shell` уходит в approval. в approval
  показывается содержимое скрипта.
- `core/verify.py` проверяет синтаксис `.py` после `write_file` / `edit_file`
  через `py_compile` с таймаутом 5 с.

**что не защищено (честно):**

- **`ctypes.windll`**  прямой вызов win32 из одобренного скрипта.
  python-уровень это не ловит.
- **c-extension'ы** (numpy, pil, torch) читают файлы через свою libc, минуя
  все патчи.
- **утверждённый код пользователем**  если юзер нажал `y`, это его
  ответственность. sandbox защищает от случайностей и ленивых атак, не от
  я сам разрешил.
- **реальный os-containment** (windows job object, appcontainer)  отдельная
  итерация, не в этой версии.

**рекомендации:**

- работай под отдельным пользователем ос, если данные чувствительны.
- не отключай `.gitignore` для `logs/` и `workspace/`  там могут быть
  прочитанные агентом файлы.

## тесты

```powershell
python tests/run_all.py
```

покрытие: классификатор команд, sandbox, policy, retry llm, кэш одобрений,
pre-write syntax check, tokenize, network tools, denied flow.

## известные грабли

- `edit_file.old` должен быть уникальным. если строка встречается больше раз 
  вернётся ошибка. решение: добавь контекста или используй `write_file`.
- `edit_file` не любит `key:">value"`  гибрид короткой и длинной форм.
  используй `key>value`.
- `edit_file` со значениями, содержащими `:`, может ломаться на парсере.
- deepseek mla в ik_llama нестабилен, вызывает cuda-краши (issues #398,
  #1173). нужен `-mla 0` при запуске сервера.
- `--n-cpu-moe` больше 48 на 16 gb ram уводит систему в своп. рабочий
  диапазон: 2436.
- pinned memory. при больших cpu-буферах llama-server печатает
  `failed to allocate ... pinned memory`. не фатально. лечится
  `GGML_CUDA_NO_PINNED=1`.
- если модель запускает matplotlib и тот пытается писать кэш шрифтов в
  `~/.matplotlib/`  child sandbox это блокирует. картинка всё равно
  сохраняется в workspace, ошибка не критичная.

## если что-то сломалось

**тул не появился.** перезапусти `main.py` и посмотри на строки
`[tools] loaded N module(s)`. если N меньше, чем файлов в папке  там
 traceback, читай его.

**модель галлюцинирует `<result>` без вызова тула.** сработает
`fabricated_result` retry в `agent/agent.py`. если повторяется  уменьши
`TEMPERATURE`, поставь `thinking_budget=0`.

**модель зациклилась.** сработает `loop_guard`. в чате появится
`auto-recovering (N/3)`. если после 3 попыток всё ещё цикл  напиши
`/continue`.

**парсер не находит tool-call.** проверь, не обёрнут ли он в блок кода.
открой `core/parser.py`, `extract_calls`.

**tool падает с `PermissionError`.** агент лезет за пределы `workspace/`.
 tui спросит подтверждение (y/n). если хука не сработал  `core/sandbox.py`.

**контекст переполняется.** смотри нижний статус-бар. сжатие  на
`COMPRESS_AT`, семантическое резюме  на `SUMMARY_AT`. параметры в
`core/paths.py` и `core/compression.py`.

**ui выглядит криво.** `ui/app.py`, константа `CSS`. панели: `#chat-panel`,
`#stats-panel`, `#prompt`, `#status`.

## архитектура в двух словах

```text
main.py
  собирает Registry + SkillRegistry + CommandRegistry через
  load_tools / load_skills / load_commands  обход папок
  создаёт Logger и MatrixCodeApp

MatrixCodeApp
  при старте строит Agent
  на каждый ввод -> app.run_agent_turn -> Agent.ask(text, CB)

Agent.ask
  _ensure_fit (сжатие + drop при переполнении)
  _one_model_call -> llm.client.chat_stream
  extract_calls(content) из core.parser
  execute_one(call) из execution.executor
  результат -> messages.append(user)
  цикл до отсутствия tool-call'ов или лимита

CB (callbacks)
  ловит события (стрим, тулы, статус)
  обновляет ChatColumn и StatsPanel
```

ключевое: **Agent ничего не знает про ui**. он общается через callback-объект
`CB`. поэтому агента можно тестировать без tui.

## лицензия

MIT.
