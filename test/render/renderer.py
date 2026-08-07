"""Renderer 抽象接口 —— 游戏逻辑与渲染层的边界。"""

from abc import ABC, abstractmethod


class Renderer(ABC):
    """渲染器抽象基类。不同后端（Textual/Godot/...）实现此接口。"""

    @abstractmethod
    def run(self) -> None:
        """启动渲染主循环。"""
        ...
