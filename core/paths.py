"""все пути, env-переменные и константы. ни от кого не зависит."""
from __future__ import annotations

import os
from pathlib import Path

# корень проекта от этого файла
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# относительные пути считаем от корня
def _resolve_path(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


# подключение к llama-server
# --- LLM connection ---------------------------------------------------------

BASE_URL   = os.getenv("MATRIXCODE_BASE_URL", "http://127.0.0.1:8080/v1")
ENV_MODEL  = os.getenv("MATRIXCODE_MODEL", "local-model")
API_KEY    = os.getenv("MATRIXCODE_API_KEY", "sk-no-key")
TIMEOUT    = float(os.getenv("MATRIXCODE_TIMEOUT", "300"))

# параметры сэмплинга
# --- generation -------------------------------------------------------------

TEMPERATURE          = float(os.getenv("MATRIXCODE_TEMPERATURE", "0.4"))
THINKING_TEMPERATURE = float(os.getenv("MATRIXCODE_THINKING_TEMPERATURE", "1.0"))
MAX_TOKENS           = int(os.getenv("MATRIXCODE_MAX_TOKENS", "2048"))
THINKING_BUDGET      = int(os.getenv("MATRIXCODE_THINKING_BUDGET", "-1"))

# лимиты главного цикла
# --- agent loop -------------------------------------------------------------

MAX_ITERS      = int(os.getenv("MATRIXCODE_MAX_ITERS", "-1"))
MAX_TOOL_CHARS = int(os.getenv("MATRIXCODE_MAX_TOOL_CHARS", "8000"))

# сжатие контекста
# --- context management -----------------------------------------------------

CTX_DEFAULT = int(os.getenv("MATRIXCODE_CONTEXT_WINDOW", "16384"))
COMPRESS_AT = float(os.getenv("MATRIXCODE_COMPRESS_AT", "0.7"))
KEEP_TURNS  = int(os.getenv("MATRIXCODE_KEEP_TURNS", "4"))

# семантическое резюме истории
# --- semantic summary -------------------------------------------------------
SUMMARY_ENABLED  = os.getenv(
    "MATRIXCODE_SUMMARY", "1").lower() not in ("0", "false", "no", "off")
SUMMARY_AT       = float(os.getenv("MATRIXCODE_SUMMARY_AT", "0.55"))
SUMMARY_KEEP     = int(os.getenv("MATRIXCODE_SUMMARY_KEEP", "4"))
SUMMARY_MIN_MSGS = int(os.getenv("MATRIXCODE_SUMMARY_MIN_MSGS", "12"))

# пороги детектора циклов
# --- loop detection ---------------------------------------------------------

FP_REPEAT_LIMIT     = int(os.getenv("MATRIXCODE_FP_REPEAT_LIMIT", "2"))
LOOP_REPEAT_LIMIT   = int(os.getenv("MATRIXCODE_LOOP_REPEAT_LIMIT", "5"))
MAX_LOOP_RECOVERIES = int(os.getenv("MATRIXCODE_MAX_LOOP_RECOVERIES", "3"))

# раскладка проекта
# --- filesystem layout ------------------------------------------------------

LOG_DIR       = _resolve_path(os.getenv("MATRIXCODE_LOG_DIR", "logs"))
SYSTEM_FILE   = _resolve_path(os.getenv("MATRIXCODE_SYSTEM_FILE",
                                        "prompts/system.md"))
TOOLS_DIR     = _resolve_path(os.getenv("MATRIXCODE_TOOLS_DIR", "tools"))
SKILLS_DIR    = _resolve_path(os.getenv("MATRIXCODE_SKILLS_DIR", "skills"))
COMMANDS_DIR  = _resolve_path(os.getenv("MATRIXCODE_COMMANDS_DIR", "commands"))
WORKSPACE_DIR = _resolve_path(os.getenv("MATRIXCODE_WORKSPACE", "workspace"))
MEMORY_FILE   = _resolve_path(os.getenv("MATRIXCODE_MEMORY_FILE",
                                        "prompts/memory.md"))

# --- grammar (GBNF) ---------------------------------------------------------

GRAMMAR_FILE = _resolve_path(
    os.getenv("MATRIXCODE_GRAMMAR_FILE", "prompts/tools.gbnf"))
GRAMMAR_ENABLED = os.getenv(
    "MATRIXCODE_GRAMMAR", "1").lower() not in ("0", "false", "no", "off")

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# TTL одобрения пути (сек). См. ui/app.py._approval_store.
# ttl одобрения пути
APPROVAL_TTL_SEC = 600
