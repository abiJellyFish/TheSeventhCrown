"""AI 行为引擎 —— 组件匹配打分。"""
from domain.ai.discretize import discretize_state
from domain.ai.components import COMPONENTS
from domain.entity import Entity


class BehaviorEngine:
    def __init__(self):
        pass

    def decide(self, npc: Entity, extra_keys: set = None) -> list[tuple[str, float]]:
        state_keys = set(discretize_state(npc))
        if extra_keys:
            state_keys |= extra_keys

        comp_names = npc.behavior_table
        overrides = npc.behavior_overrides

        candidates = []
        for name in comp_names:
            comp = COMPONENTS.get(name)
            if comp is None:
                raise ValueError(
                    f"行为组件未注册: {name} (实体: {getattr(npc, 'name', id(npc))})"
                )
            match = True
            for cond_val in comp.conditions.values():
                if cond_val not in state_keys:
                    match = False
                    break
            if not match:
                continue
            weight = overrides.get(name, comp.weight)
            candidates.append((name, weight))

        candidates.sort(key=lambda x: x[1], reverse=True)
        if not candidates:
            candidates.append(("idle", 0.0))
        return candidates
