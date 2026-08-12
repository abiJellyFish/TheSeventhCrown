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
    "pickup":        BehaviorComponent("pickup", 0.65, {"env": "env:items_nearby"}, 1),
    "forage":        BehaviorComponent("forage", 0.6, {"needs": "need:hungry", "env": "env:food_visible"}),
    "eat_food":      BehaviorComponent("eat_food", 0.9, {"needs": "need:hungry", "env": "env:food_adjacent"}),
    "hunt":          BehaviorComponent("hunt", 0.8, {"needs": "need:hungry", "env": "env:prey_nearby"}),  # 相邻→攻击，不邻→移动
    "collect":       BehaviorComponent("collect", 0.4, {"needs": "need:hungry"}),  # 仅饥饿时采集存包
    "eat_inventory": BehaviorComponent("eat_inventory", 0.55, {"needs": "need:hungry", "env": "env:has_food"}),
    "open_door":      BehaviorComponent("open_door", 0.65, {"env": "env:door_nearby"}, 1),
    "close_door":     BehaviorComponent("close_door", 0.7, {"env": "env:open_door_nearby"}, 1),
    "attack_enemy":   BehaviorComponent("attack_enemy", 0.85, {"env": "env:enemy_adjacent"}, 2),
    "approach_enemy": BehaviorComponent("approach_enemy", 0.7, {"env": "env:enemy_visible"}, 1),
    "flee":          BehaviorComponent("flee", 0.8, {"needs": "hp:critical"}),
    "idle":          BehaviorComponent("idle", 0.1, {}),
    "rest":          BehaviorComponent("rest", 0.05, {}, 1),  # 始终可选，权重最低
}

# 默认行为表（creatures.json 中未定义 behavior 的生物使用）
DEFAULT_BEHAVIOR = {
    "components": ["wander", "forage", "eat_food", "eat_inventory", "flee", "idle"],
    "overrides": {}
}
