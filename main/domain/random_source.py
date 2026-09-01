"""可注入的随机数服务。"""

import random
from random import Random


class RandomSource:
    """为游戏规则提供可替换的随机数实现。"""

    def __init__(self, seed: int | None = None) -> None:
        self._random = Random(seed)

    def randint(self, start: int, end: int) -> int:
        return self._random.randint(start, end)

    def random(self) -> float:
        return self._random.random()

    def choice(self, values):
        return self._random.choice(values)

    def seed(self, value: int | None) -> None:
        self._random.seed(value)


DEFAULT_RANDOM = RandomSource()
