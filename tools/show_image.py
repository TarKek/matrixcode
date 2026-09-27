"""show_image — рендерит растровую картинку (PNG/JPG) в ANSI-полублоки.

Терминал не умеет показывать картинки напрямую (в Windows Terminal —
точно нет). Мы используем Unicode символ ▀ (верхний полублок):
верхняя половина символа — это fg-цвет (верхний пиксель), нижняя —
bg-цвет (нижний пиксель). Так любой пиксель превращается в половину
символьной ячейки.

ВАЖНО: сама ANSI-картинка печатается в stdout — её перехватывает
executor через contextlib.redirect_stdout и отдаёт в UI через
on_output. В <result> возвращается только короткий статус. Если
положить ANSI-картинку в <result>, она (а) уедет в контекст модели
на десятки тысяч символов, (б) обрежется MAX_TOOL_CHARS, (в) всё
равно не отрендерится в чате.

Требует Pillow. Если его нет: pip install Pillow
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


# decompression bomb: Pillow сам предупреждает при >89M пикселей,
# но в терминал рендерится всё равно огромный PNG. Ограничиваем.
_MAX_PIXELS = 25_000_000
_MAX_BYTES = 25_000_000


# lazy-импорт Pillow с понятной ошибкой
def _get_lanczos():
    """Pillow ≥ 9.1 перенёс константы в Image.Resampling."""
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        return getattr(resampling, "LANCZOS", None)
    return getattr(Image, "LANCZOS", None)


# рендер картинки в ansi-полублоки
def _run(path: str, width: int = 80) -> str:
    if Image is None:
        return ("error: Pillow not installed. "
                "Ask the user to run: pip install Pillow")

    # страховка: если coerce_args по какой-то причине не сработал (старая
    # версия executor'а), width придёт строкой. Упадём здесь с ясной
    # ошибкой, а не в недрах PIL.
    try:
        width = int(width)
    except (TypeError, ValueError):
        return f"error: width must be an integer, got {width!r}"
    width = max(1, min(width, 400))

    p = Path(path)
    if not p.is_file():
        return f"error: no such file: {path}"

    # размер файла: 25 MB PNG разворачивается в ~100 MB RGBA.
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"error: cannot stat {path}: {e}"
    if size > _MAX_BYTES:
        return (f"error: refusing to decode {size} bytes  image "
                f"exceeds {_MAX_BYTES} byte limit. Use a smaller file.")

    try:
        img = Image.open(p).convert("RGBA")
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"

    # decompression bomb: не пытаемся ресайзить гигапиксельные картинки.
    px = img.width * img.height
    if px > _MAX_PIXELS:
        return (f"error: refusing to render {img.width}x{img.height} "
                f"({px} px)  exceeds {_MAX_PIXELS} pixel limit. "
                f"Downscale the image first.")

    # терминальный пиксель ~в 2 раза выше, чем шире. Делим высоту на 2,
    # чтобы пропорции сохранились.
    aspect = img.height / img.width
    height = max(1, int(width * aspect / 2))
    target_size = (width, height * 2)

    resample = _get_lanczos()
    try:
        if resample is not None:
            img = img.resize(target_size, resample)
        else:
            img = img.resize(target_size)
    except Exception as e:
        return f"error during resize: {type(e).__name__}: {e}"

    # PIL Image.tobytes() → RGBA-байты row-major. Обходим PixelAccess
    # (у него кривые stubs), работаем с сырым буфером.
    raw = img.tobytes()
    stride = width * 4

    lines: list[str] = []
    for y in range(height):
        row: list[str] = []
        top_off_base = (y * 2) * stride
        bot_off_base = (y * 2 + 1) * stride
        # дедуп ANSI: если верх/низ того же цвета, что у соседа слева,
        # escape не переписываем. На сплошных заливках (как белый фон
        # вокруг сердца) это экономит ~90% байтов.
        prev: tuple[int, int, int, int, int, int] | None = None
        for x in range(width):
            t = top_off_base + x * 4
            b = bot_off_base + x * 4
            r1, g1, b1, a1 = raw[t], raw[t + 1], raw[t + 2], raw[t + 3]
            r2, g2, b2, a2 = raw[b], raw[b + 1], raw[b + 2], raw[b + 3]
            # полупрозрачные пиксели подмешиваем к чёрному — иначе на
            # светлом терминале картинка выглядит ярче, чем на тёмном.
            if a1 < 255:
                r1 = r1 * a1 // 255
                g1 = g1 * a1 // 255
                b1 = b1 * a1 // 255
            if a2 < 255:
                r2 = r2 * a2 // 255
                g2 = g2 * a2 // 255
                b2 = b2 * a2 // 255
            pair = (r1, g1, b1, r2, g2, b2)
            if pair != prev:
                row.append(
                    f"\x1b[38;2;{r1};{g1};{b1}m"
                    f"\x1b[48;2;{r2};{g2};{b2}m"
                )
                prev = pair
            row.append("▀")
        row.append("\x1b[0m")
        lines.append("".join(row))

    art = "\n".join(lines)
    # print → executor ловит через redirect_stdout → on_output → UI.
    print(art)
    return (f"ok: rendered {path} at {width}×{height} terminal cells "
            f"({len(art)} bytes of ANSI output). "
            f"The image is visible to the user in the chat panel.")


def register(reg):
    reg.add(
        "show_image",
        '<call- show_image: path:"chart.png" width:80 -call>\n'
        "Renders a raster image (PNG/JPG/BMP) directly in the terminal chat "
        "as colored Unicode blocks. Use this after matplotlib "
        "savefig('chart.png') to actually SEE the plot — you cannot view "
        "GUI windows or open image viewers.\n"
        "Args: path (string, required), width (int, default 80) — number "
        "of terminal columns the image should occupy.\n"
        "Result: colored ANSI image visible in the chat.",
        _run,
    )
