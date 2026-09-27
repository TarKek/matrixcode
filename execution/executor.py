"""вызов одного тула: coerce_args + перехват ошибок + лог.

Оборачивает вызов в sandbox-флаг (_tls.active) — только внутри
этого вызова файловые операции агента проверяются на workspace.
Перед вызовом — sandbox.guard_kwargs: preflight-проверка всех
kwargs с путевыми именами. Это ловит тулы, которые читают файлы
не через builtins.open (Pillow) или через API вне os.*-патчей
(os.startfile).
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import typing

from core import sandbox
from core.display import truncate
from core.logger import Logger, strip_ansi
from core.paths import MAX_TOOL_CHARS
from core.registries import Registry

_STR_TO_TYPE = {"int": int, "float": float, "bool": bool, "str": str}


# приводим args из парсера к сигнатуре fn
def coerce_args(fn, args: dict) -> dict:
    """Приводит строковые значения к типам из сигнатуры тула.

    ВАЖНО: все тулы объявлены с `from __future__ import annotations`,
    поэтому `inspect.signature(fn).parameters["x"].annotation` возвращает
    СТРОКУ ("int", "float", ...), а не сам тип. Проверка `ann is int`
    тогда всегда False — именно из-за этого `width:"80"` доезжал до тела
    как строка и падал на `"80" * aspect`. Разворачиваем через
    typing.get_type_hints: он резолвит строковые аннотации в реальные типы.
    """
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        # какой-то тип в аннотации не резолвится (например, forward ref
        # на класс, которого нет в globals модуля тула). Не страшно —
        # откатимся на покомпонентную эвристику ниже.
        hints = {}
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return args

    out = {}
    for k, v in args.items():
        p = sig.parameters.get(k)
        ann = hints.get(k)
        if ann is None and p is not None:
            ann = p.annotation
        # если get_type_hints не отработал, а аннотация всё ещё строка —
        # распознаём по имени типа. Это последний рубеж, но он покрывает
        # 99% случаев (int / float / bool / str).
        if isinstance(ann, str):
            ann = _STR_TO_TYPE.get(ann, ann)

        if ann is int:
            try:
                out[k] = int(v)
                continue
            except (TypeError, ValueError):
                pass
        elif ann is float:
            try:
                out[k] = float(v)
                continue
            except (TypeError, ValueError):
                pass
        elif ann is bool:  # noqa: SIM102
            if isinstance(v, str):
                out[k] = v.lower() in ("1", "true", "yes", "on")
                continue
        out[k] = v
    return out


# понятное сообщение при несовпадении аргументов
def _bad_args_message(fn, parsed: dict, exc: TypeError) -> str:
    """Понятная ошибка для модели: что пропущено, что лишнее, пример."""
    try:
        sig = inspect.signature(fn)
    except Exception:
        return f"error: bad args: {exc}"

    required = [p.name for p in sig.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                               inspect.Parameter.KEYWORD_ONLY)]
    known = {p.name for p in sig.parameters.values()}
    provided = list((parsed.get("args") or {}).keys())

    missing = [r for r in required if r not in provided]
    unknown = [p for p in provided if p not in known]

    # если сигнатура валидна (нет missing / unknown), а TypeError всё равно
    # прилетел — это ошибка ВНУТРИ функции, не в аргументах. Раньше здесь
    # выдавалось «bad args (...). Required: path» — модель видела это,
    # думала «path же передан!» и перебирала аргументы по кругу. Теперь
    # отдаём настоящий текст ошибки.
    if not missing and not unknown:
        return f"error: {parsed['name']}: {type(exc).__name__}: {exc}"

    bits = []
    if missing:
        bits.append("missing " + ", ".join(missing))
    if unknown:
        bits.append("unknown " + ", ".join(unknown))
    detail = "; ".join(bits)

    example = " ".join(f'{r}:"…"' for r in required)
    name = parsed["name"]
    return (f"error: {name}: bad args ({detail}). "
            f"Required: {', '.join(required)}. "
            f'Example: <call- {name}: {example} -call>')


# один tool-call: guard -> fn -> результат
async def execute_one(
    c: dict,
    registry: Registry,
    logger: Logger,
    on_output=None,
    on_diff=None,
) -> tuple[str, bool, str]:
    """Возвращает (result_string, is_error, tool_name).

    on_output(text, name) — stdout тула.
    on_diff(path, old_text, new_text) — для edit_file / write_file:
        вызывается после успешного выполнения, если содержимое изменилось.
    """
    from pathlib import Path

    parsed = c["parsed"]
    name = (parsed or {}).get("name", "?")
    is_err = False
    captured = ""
    buf = io.StringIO()

    # пред-снимок для edit_file/write_file: читаем файл ДО запуска тула.
    # пропускаем, если target вне workspace — там sandbox всё равно
    # откажет, а читать чужое на этапе подготовки незачем.
    pre_snapshot: str | None = None
    diff_target: str = ""
    if parsed and not parsed.get("error"):  # noqa: SIM102
        if parsed.get("name") in ("edit_file", "write_file"):
            diff_target = (parsed.get("args") or {}).get("path", "")
            if diff_target and sandbox.is_in_workspace(diff_target):
                p = Path(diff_target)
                try:
                    pre_snapshot = (p.read_text(encoding="utf-8")
                                    if p.is_file() else "")
                except Exception:
                    pre_snapshot = None  # не читается — пропустим diff

    if parsed is None:
        res = "<result>error: malformed call — no tool name</result>"
        is_err = True
    elif parsed["error"]:
        res = f"<result>error: {parsed['error']}</result>"
        is_err = True
    elif parsed["name"] not in registry.tools:
        res = f"<result>error: unknown tool '{parsed['name']}'</result>"
        is_err = True
    else:
        fn = registry.tools[parsed["name"]]["fn"]
        try:
            kwargs = coerce_args(fn, parsed["args"])
            loop = asyncio.get_running_loop()

            def _run():
                sandbox._tls.active = True
                try:
                    # preflight: проверяем ВСЕ kwargs с путевыми именами.
                    # ловит тулы, которые ходят в файлы не через
                    # builtins.open (Pillow) или вне os.*-патчей
                    # (os.startfile). См. sandbox.PATH_ARG_NAMES.
                    sandbox.guard_kwargs(
                        kwargs, prefix=f"{parsed['name']}:")
                    with contextlib.redirect_stdout(buf):
                        return fn(**kwargs)
                finally:
                    sandbox._tls.active = False

            out = await loop.run_in_executor(None, _run)
            out = truncate(str(out), MAX_TOOL_CHARS)
            res = f"<result>{out}</result>"
        except sandbox.ApprovalDenied as e:
            res = (f"<result>error: user denied  {e}\n"
                   "Do NOT retry the same path or the same args. "
                   "Continue with the next step of the plan."
                   "</result>")
            is_err = True
        except PermissionError as e:
            res = f"<result>error: {e}</result>"
            is_err = True
        except TypeError as e:
            res = f"<result>{_bad_args_message(fn, parsed, e)}</result>"
            is_err = True
        except Exception as e:
            res = f"<result>error: {type(e).__name__}: {e}</result>"
            is_err = True
        captured = (buf.getvalue()
                    .replace("\r\n", "\n").replace("\r", "\n"))

    logger.event("tool_result", call=c["raw"], result=res,
                 result_chars=len(res), is_error=is_err,
                 captured=strip_ansi(captured)[:2000] if captured else "")

    if on_output is not None and captured.strip():
        try:
            await on_output(captured, name)
        except Exception as e:
            logger.event("cb_error", method="on_tool_output",
                         error=f"{type(e).__name__}: {e}")

    # diff — только для успешных edit_file / write_file.
    if (not is_err and on_diff is not None
            and pre_snapshot is not None and diff_target):
        try:
            p = Path(diff_target)
            new_text = (p.read_text(encoding="utf-8")
                        if p.is_file() else None)
            if new_text is not None and new_text != pre_snapshot:
                await on_diff(diff_target, pre_snapshot, new_text)
        except Exception as e:
            logger.event("cb_error", method="on_tool_diff",
                         error=f"{type(e).__name__}: {e}")

    return res, is_err, name
