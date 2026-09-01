"""状态效果数据类。"""
from dataclasses import dataclass


@dataclass
class StatusEffect:
    """状态效果。duration=None 表示永久（如 incapacitated），>0 表示剩余钟摆数。"""
    name: str
    duration: int | None = None
