"""偷窃系统（P1 3.3）—— 纯规则，无 UI。

规则：偷窃是动作面板选项，瞄准相邻目标后选择一件物品。
物品价值每 1 GP 耗 1 钟摆；目标感知检定作难度；每钟摆做一次敏捷检定，
全部通过才偷成，任一失败即被发现。隐匿状态敏捷检定具有优势。
"""
from domain.dice import roll_d20, check_total
from domain.trade import price_to_copper


def steal_cost(item) -> int:
    """偷窃耗时（钟摆）= 物品价值 GP 数（向下取整），至少 1。"""
    gp = price_to_copper(item.price) // 100
    return max(1, gp)


def make_steal_dc(target) -> int:
    """目标感知检定结果作为偷窃难度 DC。"""
    return check_total(target, roll_d20(), target.stat_adjust("wis"))


def try_steal_roll(player, dc: int, hidden: bool = False) -> bool:
    """一次敏捷检定：骰值 + 敏捷调整 >= DC 通过。隐匿状态优势。"""
    roll = roll_d20(advantage=1) if hidden else roll_d20()
    return check_total(player, roll, player.stat_adjust("dex")) >= dc


def resolve_steal(player, target, item, hidden: bool = False) -> dict:
    """完整偷窃一次：cost 个钟摆内逐钟摆敏捷检定，全部通过才成功。

    返回 {"success": bool, "cost": int, "dc": int, "failed_at": int | None}。
    failed_at 为第几次检定失败（1-based），成功时为 None。
    """
    dc = make_steal_dc(target)
    cost = steal_cost(item)
    for tick in range(1, cost + 1):
        if not try_steal_roll(player, dc, hidden):
            return {"success": False, "cost": cost, "dc": dc, "failed_at": tick}
    return {"success": True, "cost": cost, "dc": dc, "failed_at": None}
