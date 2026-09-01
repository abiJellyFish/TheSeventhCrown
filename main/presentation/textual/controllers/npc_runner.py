"""NPC 控制器兼容模块。

NPC 行为统一由 domain.ai.npc_runner.NpcBehaviorMixin 执行。
此模块保留空混入类，避免改变 GameScreen 的组合结构。
"""


class NpcRunnerMixin:
    """NPC 行为已迁移到领域层。"""

