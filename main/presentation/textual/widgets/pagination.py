"""按窗口高度分页的文本内容工具。"""

import re
from math import ceil

from rich.text import Text


_BRACKET_PATTERN = re.compile(
    r"(?<!\\)(\[\[[^\]]*\]\]|\[([^\]]*)\])"
)
_RICH_TAGS = {"bold", "dim", "red", "green", "yellow", "blue", "/"}
_STYLE_TAG = re.compile(r"\[(bold|dim|red|green|yellow|blue|/)\]")


def _display_line_count(line: str, width: int) -> int:
    """按终端单元格宽度估算一行实际占用的显示行数。"""
    if width <= 0:
        return 1
    plain = to_renderable(line).plain
    return max(1, ceil(Text(plain).cell_len / width))


def escape_key_hints(text: str) -> str:
    """保留快捷键文本，转义未知方括号，并保留合法 Rich 样式。"""

    def replace_brackets(match: re.Match[str]) -> str:
        token = match.group(1)
        tag = match.group(2)
        if token.startswith("[["):
            return f" {token[2:-2]} "
        if tag in _RICH_TAGS:
            return token
        return tag if tag is not None else token

    return _BRACKET_PATTERN.sub(replace_brackets, text)


def to_renderable(text: str) -> Text:
    """将内容和受控样式分开构造为 Text，避免内容再次进入 Rich markup 解析。"""
    sanitized = escape_key_hints(text)
    rendered = Text()
    cursor = 0
    style: str | None = None

    def append_segment(value: str, active_style: str | None) -> None:
        if not value:
            return
        is_pagination_marker = (
            active_style == "dim"
            and value.strip().startswith(("上方剩余", "下方剩余"))
        )
        rendered.append(
            value,
            style=active_style if is_pagination_marker
            else f"white {active_style}" if active_style else "white",
        )

    for match in _STYLE_TAG.finditer(sanitized):
        if match.start() > cursor:
            append_segment(sanitized[cursor:match.start()], style)
        tag = match.group(1)
        style = None if tag == "/" else tag
        cursor = match.end()
    if cursor < len(sanitized):
        append_segment(sanitized[cursor:], style)
    return rendered


def paginate_lines(
    lines: list[str],
    height: int,
    offset: int,
    *,
    page_size: int = 5,
    from_top: bool = False,
    width: int = 0,
) -> tuple[str, int]:
    """返回分页文本和规范化后的偏移量。面板可选择从顶部开始分页。"""
    if not lines:
        return "", 0

    window_height = max(1, height)
    normalized_offset = min(max(0, offset), max(0, len(lines) - 1))
    if not from_top:
        visible_height = window_height
        for _ in range(3):
            start = max(0, len(lines) - visible_height - normalized_offset)
            end = min(len(lines), start + visible_height)
            above = start
            below = max(0, len(lines) - end)
            marker_count = int(above > 0) + int(below > 0)
            next_height = max(1, window_height - marker_count)
            if next_height == visible_height:
                break
            visible_height = next_height
    else:
        line_heights = [_display_line_count(line, width) for line in lines]
        start = normalized_offset
        for _ in range(len(lines) + 1):
            above = start
            has_below = len(lines) > start
            available_height = max(
                1, window_height - int(above > 0) - int(has_below)
            )
            end = start
            used_height = 0
            while (
                end < len(lines)
                and used_height + line_heights[end] <= available_height
            ):
                used_height += line_heights[end]
                end += 1
            next_below = end < len(lines)
            if next_below == has_below:
                break
            has_below = next_below
        below = max(0, len(lines) - end)

    result: list[str] = []
    if above:
        result.append(f"[dim]上方剩余 {above} 行[/]")
    result.extend(lines[start:end])
    if below:
        result.append(f"[dim]下方剩余 {below} 行[/]")
    return "\n".join(result), normalized_offset
