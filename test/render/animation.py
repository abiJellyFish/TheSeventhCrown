"""动画数据定义 —— ASCII 95 字符集，纯数据，可存 JSON。

参考: test/docs/补充1.md 动画部分。
"""

from dataclasses import dataclass, field


@dataclass
class AnimationCell:
    """动画中的单个字符。"""
    dx: int       # 相对原点的列偏移
    dy: int       # 相对原点的行偏移
    ch: str       # ASCII 字符 (码点 32-126)
    color: str    # 颜色名


@dataclass
class AnimationDef:
    """一个动画定义（纯数据）。"""
    name: str
    frames: list[list[AnimationCell]]
    frame_duration: float = 0.1
    loop: bool = False


# ── 预定义动画 ──

ANIMATIONS: dict[str, AnimationDef] = {
    "slash_right": AnimationDef(
        name="slash_right",
        frames=[
            [AnimationCell(0, 0, "/", "red")],
            [AnimationCell(0, 0, "-", "bright_yellow"),
             AnimationCell(1, 0, "-", "bright_yellow")],
            [AnimationCell(1, 0, "\\", "red")],
        ],
        frame_duration=0.05,
    ),
    "magic_missile": AnimationDef(
        name="magic_missile",
        frames=[
            [AnimationCell(0, 0, "*", "bright_magenta")],
            [AnimationCell(1, 0, "*", "bright_magenta")],
            [AnimationCell(2, 0, "+", "bright_cyan")],
        ],
        frame_duration=0.08,
    ),
    "sleep_zzz": AnimationDef(
        name="sleep_zzz",
        frames=[
            [AnimationCell(0, -1, "z", "white")],
            [AnimationCell(0, -1, "Z", "white")],
        ],
        frame_duration=0.5,
        loop=True,
    ),
    "fire_tile": AnimationDef(
        name="fire_tile",
        frames=[
            [AnimationCell(0, 0, "~", "red")],
            [AnimationCell(0, 0, "~", "yellow")],
        ],
        frame_duration=0.3,
        loop=True,
    ),
}
