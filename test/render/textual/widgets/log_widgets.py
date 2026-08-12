"""日志组件 —— LogView 基类 + 动作日志 + 场景日志。"""

from textual.widgets import Static


class LogView(Static):
    """日志视图基类。"""
    messages: list[str] = []
    _max_history: int = 200
    _trim_to: int = 100
    _scroll_offset: int = 0   # 0=最新，正值=向上翻

    def scroll_up(self) -> None:
        max_offset = max(0, len(self.messages) - 1)
        self._scroll_offset = min(max_offset, self._scroll_offset + 1)
        self.refresh()

    def scroll_down(self) -> None:
        self._scroll_offset = max(0, self._scroll_offset - 1)
        self.refresh()

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > self._max_history:
            self.messages = self.messages[-self._trim_to:]
        self._scroll_offset = 0  # 新消息重置滚动
        self.refresh()

    def render(self) -> str:
        if not self.messages:
            return ""
        h = max(self.size.height, 6)
        if self._scroll_offset > 0:
            start = max(0, len(self.messages) - h - self._scroll_offset)
            end = len(self.messages) - self._scroll_offset
            return "\n".join(self.messages[start:end])
        return "\n".join(self.messages[-h:])


class ActionLog(LogView):
    """动作日志（左侧）。"""
    pass


class SceneLog(LogView):
    """场景描述日志（右侧）。"""

    def set_scene(self, lines: list[str]) -> None:
        filtered = [l for l in lines if l]
        if filtered != self.messages:
            self.messages = filtered
            self.refresh()
