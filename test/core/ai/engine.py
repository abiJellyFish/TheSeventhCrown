"""AI 行为引擎 —— 纯查表 + Counter 累加，无 if-else 分支。"""

from collections import Counter

from core.ai.discretize import discretize_state
from core.entity import Creature


class BehaviorEngine:
    """AI 行为引擎。运行时单层循环，复杂度 O(匹配键数 × 平均动作数)。"""

    def __init__(self, raw_templates: dict):
        """加载并预乘权重。

        Args:
            raw_templates: {模板名: {_weights: {...}, 维度: {键: {动作: 分数}}}}
        """
        self._tables: dict[str, dict[str, dict[str, float]]] = {}
        self._filters: dict[str, dict[str, str]] = {}

        for name, raw in raw_templates.items():
            weights = raw["_weights"]
            flat: dict[str, Counter[str]] = {}

            for dim, weight in weights.items():
                dim_data = raw.get(dim, {})
                for key, actions in dim_data.items():
                    if key not in flat:
                        flat[key] = Counter()
                    for action, score in actions.items():
                        flat[key][action] += score * weight

            # Counter → dict
            self._tables[name] = {k: dict(v) for k, v in flat.items()}
            self._filters[name] = raw.get("_hard_filters", {})

    def decide(
        self, npc: Creature,
        enemy_count: int = 0,
        ally_count: int = 0,
        power_ratio: float = 1.0,
    ) -> tuple[str, float]:
        """NPC 决策。

        Returns:
            (动作名, 得分)
        """
        keys = discretize_state(npc, enemy_count, ally_count, power_ratio)
        table = self._tables.get(npc.template_name, {})
        filters = self._filters.get(npc.template_name, {})

        # 单层循环
        scores: Counter[str] = Counter()
        for key in keys:
            entry = table.get(key)
            if entry:
                scores.update(entry)

        # _default 兜底
        default = table.get("_default")
        if default:
            scores.update(default)

        # 硬过滤
        for action in tuple(scores):
            cond = filters.get(action)
            if cond and not npc.meets_condition(cond):
                del scores[action]

        if not scores:
            return ("idle", 0.0)

        best = scores.most_common(1)[0]
        return best
