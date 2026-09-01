"""领域行动队列。"""
from collections import deque
from domain.action import Action


class ActionQueue:
    """先进先出；后续行动只能追加，不递归执行。"""

    def __init__(self) -> None:
        self._items: deque[Action] = deque()

    def append(self, action: Action) -> None:
        self._items.append(action)

    def pop(self) -> Action | None:
        return self._items.popleft() if self._items else None

    def __bool__(self) -> bool:
        return bool(self._items)
