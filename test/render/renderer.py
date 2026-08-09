"""渲染器抽象接口 —— 预留模块。

当前 MVP 阶段使用 Textual 作为唯一渲染后端（MVPApp 直接继承 textual.app.App）。
本接口为 v1.0 多渲染后端（Godot 等）预留，届时新后端实现此接口。
MVP 阶段不强制使用，详见 待定计划1.md P3。
"""

from abc import ABC, abstractmethod


class Renderer(ABC):
    """渲染器抽象基类。不同后端（Textual/Godot/...）实现此接口。"""

    @abstractmethod
    def run(self) -> None:
        """启动渲染主循环。"""
        ...
