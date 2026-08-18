"""阵营关系 —— 敌对/同盟/态度判定（FACTION_RELATIONS + 推导函数）。"""

# ═══════════════════════════════════════════════════
# 阵营关系
# ═══════════════════════════════════════════════════

FACTION_RELATIONS = {
    "守序": {"allies": ["守序"], "enemies": ["混乱"]},
    "混乱": {"allies": ["混乱"], "enemies": ["守序"]},
    "中立": {"allies": [],        "enemies": []},
}


def are_hostile(a: "Entity", b: "Entity") -> bool:
    """两生物是否敌对。显式态度优先，无记录时按阵营默认推导。"""
    if a is b:
        return False
    # 显式态度优先
    a_att = a._attitude.get(id(b))
    b_att = b._attitude.get(id(a))
    if a_att == "敌对" or b_att == "敌对":
        return True
    if a_att == "友好" or b_att == "友好":
        return False
    # 无显式态度 → 按阵营默认
    if a.faction == b.faction:
        return False  # 同阵营默认友好
    enemies = FACTION_RELATIONS.get(a.faction, {}).get("enemies", [])
    return b.faction in enemies


def get_attitude(a: "Entity", b: "Entity") -> str:
    """获取 a 对 b 的态度："友好"|"冷漠"|"敌对"。与 are_hostile 共用推导逻辑。"""
    att = a._attitude.get(id(b))
    if att:
        return att
    if a.faction == b.faction:
        return "友好"
    enemies = FACTION_RELATIONS.get(a.faction, {}).get("enemies", [])
    if b.faction in enemies:
        return "敌对"
    return "冷漠"


def is_ally(a: "Entity", b: "Entity") -> bool:
    """两生物是否同盟（同阵营，且无显式敌对态度）。"""
    if a is b:
        return True
    return a.faction == b.faction
