"""AI 行为组件 —— 全局定义，生物只需声明使用哪些。"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BehaviorComponent:
    name: str
    weight: float
    conditions: dict = field(default_factory=dict)  # {"needs": "need:hungry", "env": "env:food_nearby"}
    cost: int = 1                     # 动作耗时（钟摆）


# 全局组件表（执行函数在 game_state.py 中，通过名称分发）
COMPONENTS = {
    "wander":        BehaviorComponent("wander", 0.2, {}),  # 始终可选，权重低，有更好动作时自动被覆盖
    "forage":        BehaviorComponent("forage", 0.6, {"needs": "need:hungry", "env": "env:food_visible"}),
    "eat_food":      BehaviorComponent("eat_food", 0.9, {"needs": "need:hungry", "env": "env:food_adjacent"}),
    "hunt":          BehaviorComponent("hunt", 0.8, {"needs": "need:hungry", "env": "env:prey_nearby"}),  # 相邻→攻击，不邻→移动
    "collect":       BehaviorComponent("collect", 0.4, {}),  # 无条件，饱腹采集存包，饥饿时 eat_food 高分自然覆盖
    "eat_inventory": BehaviorComponent("eat_inventory", 1.0, {"needs": "need:starving", "env": "env:has_food"}),
    "flee":          BehaviorComponent("flee", 0.8, {"needs": "hp:critical"}),
    "idle":          BehaviorComponent("idle", 0.1, {}),
    "rest":          BehaviorComponent("rest", 0.05, {}, 1),  # 始终可选，权重最低
}

# 默认行为表（creatures.json 中未定义 behavior 的生物使用）
DEFAULT_BEHAVIOR = {
    "components": ["wander", "forage", "eat_food", "eat_inventory", "flee", "idle"],
    "overrides": {}
}
