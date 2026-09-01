"""日志组件 —— LogView 基类 + 动作日志 + 场景日志。"""

from textual.widgets import Static

from presentation.textual.widgets.pagination import paginate_lines, to_renderable


class LogView(Static):
    """日志视图基类。"""
    _max_history: int = 500
    _trim_to: int = 500
    _scroll_offset: int = 0   # 0=最新，正值=向上翻

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)
        self.messages: list[str] = []
        self._scroll_offset = 0

    def _expanded_lines(self) -> list[str]:
        """消息展开为显示行（处理消息内显式换行），保证滚动/截断按行而非按消息条数。"""
        lines = []
        for msg in self.messages:
            lines.extend(msg.split("\n") if msg else [""])
        return lines

    def scroll_up(self) -> None:
        max_offset = max(0, len(self._expanded_lines()) - 1)
        self._scroll_offset = min(max_offset, self._scroll_offset + 5)
        self.refresh()

    def scroll_down(self) -> None:
        self._scroll_offset = max(0, self._scroll_offset - 5)
        self.refresh()

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > self._max_history:
            self.messages = self.messages[-self._trim_to:]
        self._scroll_offset = 0  # 新消息重置滚动
        self.refresh()

    def render(self) -> str:
        try:
            content_region = self.content_region
        except (AttributeError, RuntimeError):
            content_region = None
        height = (
            content_region.height
            if content_region is not None and content_region.height > 0
            else self.size.height
        )
        page, self._scroll_offset = paginate_lines(
            self._expanded_lines(),
            height or len(self._expanded_lines()) or 1,
            self._scroll_offset,
            width=getattr(content_region, "width", 0),
        )
        return to_renderable(page)


class ActionLog(LogView):
    """动作日志（左侧）。"""
    pass


class SceneLog(LogView):
    """战斗日志（右侧）。"""

    def set_scene(self, lines: list[str]) -> None:
        """兼容旧接口；战斗日志不再由场景刷新覆盖。"""
        max_offset = max(0, len(lines) - 1)
        self._scroll_offset = min(self._scroll_offset, max_offset)
