"""日志组件 —— LogView 基类 + 动作日志 + 场景日志。"""

from textual.widgets import Static


class LogView(Static):
    """日志视图基类。"""
    messages: list[str] = []
    _max_history: int = 200
    _trim_to: int = 100

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > self._max_history:
            self.messages = self.messages[-self._trim_to:]
        self.refresh()

    def render(self) -> str:
        if not self.messages:
            return ""
        h = max(self.size.height, 6)
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
