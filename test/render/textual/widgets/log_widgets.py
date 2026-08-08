"""日志组件 —— 动作日志 + 场景日志。"""

from textual.widgets import Static


class ActionLog(Static):
    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200:
            self.messages = self.messages[-100:]
        self.refresh()

    def render(self) -> str:
        if not self.messages:
            return ""
        h = max(self.size.height, 6)
        return "\n".join(self.messages[-h:])


class SceneLog(Static):
    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 200:
            self.messages = self.messages[-100:]
        self.refresh()

    def set_scene(self, lines: list[str]) -> None:
        filtered = [l for l in lines if l]
        if filtered != self.messages:
            self.messages = filtered
            self.refresh()

    def render(self) -> str:
        if not self.messages:
            return ""
        h = max(self.size.height, 6)
        return "\n".join(self.messages[-h:])
