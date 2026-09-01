"""游戏行动输入门控，限制连续输入但不阻塞 Textual 事件循环。"""

from collections.abc import Callable


INPUT_INTERVAL_SECONDS = 0.2


class InputGate:
    """一次行动后固定锁定输入，锁定期间不缓存后续输入。"""

    def __init__(
        self,
        schedule: Callable[[float, Callable[[], None]], object],
    ) -> None:
        self._schedule = schedule
        self._locked = False

    @property
    def locked(self) -> bool:
        return self._locked

    def begin(self) -> None:
        if self._locked:
            return
        self._locked = True
        self._schedule(INPUT_INTERVAL_SECONDS, self._unlock)

    def try_begin(self) -> bool:
        """尝试开始输入间隔；已锁定时返回 False。"""
        if self._locked:
            return False
        self.begin()
        return True

    def _unlock(self) -> None:
        self._locked = False
