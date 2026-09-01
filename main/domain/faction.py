"""阵营关系 —— 敌对/同盟/态度判定（FACTION_RELATIONS + 好感度推导函数）。"""

# ═══════════════════════════════════════════════════
# 阵营关系
# ═══════════════════════════════════════════════════

FACTION_RELATIONS = {
    "守序": {"allies": ["守序"], "enemies": ["混乱"]},
    "混乱": {"allies": ["混乱"], "enemies": ["守序"]},
    "中立": {"allies": [],        "enemies": []},
}


# ═══════════════════════════════════════════════════
# 好感度（P1 3.1）
# 相对好感度：同阵营天然 10，敌对阵营天然 -50，其余异阵营 0。
# 态度由好感度推导：>0 友好、<0 冷漠、<=-50 敌对。
# 事件可通过 adjust_favor 直接调整态度等级。
# ═══════════════════════════════════════════════════

FAVOR_ALLY = 10           # 同阵营天然好感度
FAVOR_NEUTRAL = 0         # 异阵营天然好感度（中性）
FAVOR_HOSTILE = -50       # 敌对阈值（<= 即敌对）


def default_favor(a_faction: str, b_faction: str) -> int:
    """两阵营间的天然好感度：同阵营 10，敌对阵营 -50，其余 0。"""
    if a_faction == b_faction:
        return FAVOR_ALLY
    enemies = FACTION_RELATIONS.get(a_faction, {}).get("enemies", [])
    if b_faction in enemies:
        return FAVOR_HOSTILE
    return FAVOR_NEUTRAL


def get_favor(a: "Entity", b: "Entity") -> int:
    """a 对 b 的相对好感度。无事件记录时按阵营默认推导。"""
    return a._favor.get(b.uid, default_favor(a.faction, b.faction))


def set_favor(a: "Entity", b: "Entity", value: int) -> None:
    """直接设定 a 对 b 的好感度数值。"""
    a._favor[b.uid] = value


def adjust_favor(a: "Entity", b: "Entity", level: str) -> None:
    """事件调整 a 对 b 的态度等级："友好"|"冷漠"|"敌对"。

    只向恶化/好转方向移动：好感度落到等级对应数值（若当前更极端则保持）。
    - 敌对 → <= FAVOR_HOSTILE；冷漠 → < 0；友好 → > 0。
    """
    cur = get_favor(a, b)
    if level == "敌对":
        if cur > FAVOR_HOSTILE:
            set_favor(a, b, FAVOR_HOSTILE)
    elif level == "冷漠":
        if cur >= FAVOR_NEUTRAL:
            set_favor(a, b, FAVOR_NEUTRAL - 1)
    elif level == "友好":
        if cur <= FAVOR_NEUTRAL:
            set_favor(a, b, FAVOR_NEUTRAL + 1)


def are_hostile(a: "Entity", b: "Entity") -> bool:
    """两生物是否敌对。显式态度优先，否则按好感度（<= FAVOR_HOSTILE）判定。"""
    if a is b:
        return False
    # 显式态度优先
    a_att = a._attitude.get(id(b))
    b_att = b._attitude.get(id(a))
    if a_att == "敌对" or b_att == "敌对":
        return True
    if a_att == "友好" or b_att == "友好":
        return False
    # 无显式态度 → 按好感度
    return get_favor(a, b) <= FAVOR_HOSTILE


def get_attitude(a: "Entity", b: "Entity") -> str:
    """获取 a 对 b 的态度："友好"|"冷漠"|"敌对"。显式态度优先，否则按好感度推导。"""
    att = a._attitude.get(id(b))
    if att:
        return att
    favor = get_favor(a, b)
    if favor > FAVOR_NEUTRAL:
        return "友好"
    if favor <= FAVOR_HOSTILE:
        return "敌对"
    return "冷漠"


def is_ally(a: "Entity", b: "Entity") -> bool:
    """两生物是否同盟（同阵营，且无显式敌对态度）。"""
    if a is b:
        return True
    return a.faction == b.faction
