"""通用交互系统 —— 可交互目标检测、交互类型定义、哈希表分发。

新增交互目标类型：
  1. 写一个 _detect_xxx(state) → list[InteractTarget]
  2. 追加到 _DETECTORS 列表
  3. 在 app.py 的 _INTERACT_DISPATCH 加一行
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from domain.movement import Terrain


class InteractType(Enum):
    TALK = auto()        # 生物个人交互面板
    LOOT = auto()        # 搜刮子面板
    CORPSE = auto()      # 尸体个人交互面板
    PICK = auto()        # 采摘（灌木）
    REST = auto()        # 休息（床）
    OPEN = auto()        # 开门/关门
    PICKUP = auto()      # 捡起地上物品
    ITEM = auto()        # 地面物品交互面板
    HARVEST_CROP = auto()  # 收获作物
    PICK_CROP = auto()     # 采摘（未成熟）
    CLEAR_CROP = auto()    # 清除枯萎植株


@dataclass
class InteractTarget:
    """可交互目标。"""
    label: str                          # 中文显示名，如"商人""灌木丛""关闭的门"
    interact_type: InteractType
    pos: tuple[int, int]
    creature: object | None = None      # Entity 或 None
    extra: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════
# 生物 trait → 特殊交互标记（新增 trait 只需加一行）
# ═══════════════════════════════════════════════════

# ═══════════════════════════════════════════════════
# 检测器（新增可交互类型只需追加函数到 _DETECTORS）
# ═══════════════════════════════════════════════════

def _observer_xyz(state) -> tuple[int, int, int]:
    pos = state.controlled_entity_pos
    if pos is None:
        raise ValueError("被控实体没有坐标")
    if len(pos) == 3:
        return int(pos[0]), int(pos[1]), int(pos[2])
    if len(pos) != 2:
        raise ValueError("实体坐标必须是三维")
    return int(pos[0]), int(pos[1]), int(getattr(state, "active_z", 0))


def _visible_at_height(state, pos: tuple[int, int, int]) -> bool:
    if pos[2] == _observer_xyz(state)[2]:
        return True
    return pos in getattr(state, "fov_cache", ())


def _detect_creatures(state) -> list[InteractTarget]:
    """检测相邻格生物：死亡 → CORPSE，睡眠 → TALK，其余活物 → TALK。"""
    pc, pr = _observer_xyz(state)[:2]
    results = []
    for creature, (ec, er, ez) in state.entities:
        if creature.controlled:
            continue
        if max(abs(ec - pc), abs(er - pr)) > 1:
            continue
        if not _visible_at_height(state, (ec, er, ez)):
            continue
        pos = (ec, er)
        if creature.is_dead:
            results.append(InteractTarget(
                label=f"{creature.name}的尸体",
                interact_type=InteractType.CORPSE,
                pos=pos, creature=creature,
            ))
        elif creature.has_status("濒死"):
            results.append(InteractTarget(
                label=f"{creature.name}（濒死）",
                interact_type=InteractType.TALK,
                pos=pos, creature=creature,
                extra={"dying": True},
            ))
        elif creature.has_status("睡眠"):
            results.append(InteractTarget(
                label=f"{creature.name}（睡眠）",
                interact_type=InteractType.TALK,
                pos=pos, creature=creature,
            ))
        else:
            results.append(InteractTarget(
                label=creature.name,
                interact_type=InteractType.TALK,
                pos=pos, creature=creature,
                extra={},
            ))
    return results


def _detect_doors(state) -> list[InteractTarget]:
    """检测相邻格门。"""
    pc, pr, pz = state.controlled_entity_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            door = next(
                (item for item, item_pos in state.ground_items
                 if item_pos == (pos[0], pos[1], pz)
                 and item.name in ("打开的门", "关闭的门")),
                None,
            )
            if door is not None:
                results.append(InteractTarget(
                    label=door.name, interact_type=InteractType.OPEN,
                    pos=pos, extra={"is_open": door.name == "打开的门"},
                ))
    return results


def _detect_beds(state) -> list[InteractTarget]:
    """检测相邻格床。"""
    pc, pr, pz = state.controlled_entity_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            if state.map.within_bounds(*pos) and any(
                item_pos == (pos[0], pos[1], pz) and item.name == "床铺"
                for item, item_pos in state.ground_items
            ):
                results.append(InteractTarget(
                    label="床铺", interact_type=InteractType.REST, pos=pos,
                ))
    return results


def _detect_ground_items(state) -> list[InteractTarget]:
    """检测玩家所在格及相邻格的地上物品。"""
    from domain.combat.shape import entity_reach
    pc, pr = _observer_xyz(state)[:2]
    reach = entity_reach(state.controlled_entity)
    results = []
    seen: set[tuple[int, int, int]] = set()
    for item, (ic, ir, iz) in state.ground_items:
        if max(abs(ic - pc), abs(ir - pr)) > reach:
            continue
        if not _visible_at_height(state, (ic, ir, iz)):
            continue
        pos_key = (ic, ir, iz)
        if pos_key in seen:
            continue
        seen.add(pos_key)
        items_at_tile = [
            it for it, (col, row, zz) in state.ground_items
            if (col, row, zz) == pos_key
        ]
        if items_at_tile:
            # 显示第一个物品名，堆叠物品显示总数
            total_count = sum(it.count for it in items_at_tile)
            first_item = items_at_tile[0]
            label = "灌木丛" if any("灌木" in it.name for it in items_at_tile) else first_item.name
            if total_count > 1:
                label += f" x{total_count}"
            results.append(InteractTarget(
                label=label, interact_type=InteractType.ITEM,
                pos=(ic, ir), extra={"items": items_at_tile},
            ))
    return results


def _detect_crops(state) -> list[InteractTarget]:
    """检测相邻格作物：成熟可收获、未成熟可采摘、枯萎可清除。"""
    from domain.crops import crop_label, is_crop_mature, load_seed_config

    pc, pr = state.controlled_entity_pos[:2]
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            plot = state.crops.get(pos)
            if plot is None:
                continue
            label = crop_label(state, pos)
            cfg = load_seed_config(plot.seed_name) or {}
            if plot.withered:
                itype = InteractType.CLEAR_CROP
            elif is_crop_mature(plot, cfg):
                itype = InteractType.HARVEST_CROP
            else:
                itype = InteractType.PICK_CROP
            results.append(InteractTarget(label=label, interact_type=itype, pos=pos))
    return results


# 检测器注册列表（新增目标类型只需追加函数）
_DETECTORS: list = [
    _detect_doors,
    _detect_beds,
    _detect_creatures,
    _detect_crops,
    _detect_ground_items,
]


def scan_interact_targets(state) -> list[InteractTarget]:
    """扫描玩家周围可交互目标。遍历所有检测器，聚合结果。"""
    targets = []
    for detector in _DETECTORS:
        targets.extend(detector(state))
    return targets


def item_interact_options(state, target) -> list[tuple[str, str]]:
    """物品个人面板选项。尸体走此面板：捡起、搜刮。"""
    items = target.extra.get("items", []) if target is not None else []
    creature = getattr(target, "creature", None)
    if creature is not None and getattr(creature, "is_dead", False):
        return [("pickup", "捡起"), ("loot", "搜刮")]
    options = []
    if any(getattr(item, "chest_data", None) is not None for item in items):
        options.append(("open", "打开"))
    if any("灌木" in getattr(item, "name", "") for item in items):
        options.append(("pick", "采摘"))
    can_pickup = any(
        getattr(getattr(item, "obstacle_type", None), "value",
                getattr(item, "obstacle_type", None)) != "full"
        and getattr(item, "can_pickup", True)
        for item in items
    )
    if can_pickup:
        options.append(("pickup", "捡起"))
    return options


def creature_interact_options(state, creature) -> list[tuple[str, str]]:
    """对象个人面板选项：(id, 标签)。能显示的才列入。"""
    from domain.faction import are_hostile, get_attitude
    from domain.quest import quests_by_giver

    if creature is None or getattr(creature, "is_dead", False):
        return []
    player = getattr(state, "controlled_entity", None)

    options = [("talk", "交谈")]
    beast = getattr(creature, "body_type", "") == "beast"
    if player is not None and not beast and not are_hostile(creature, player):
        options.append(("trade", "交易"))
    if (
        player is not None
        and not beast
        and not getattr(creature, "party_member", False)
        and get_attitude(creature, player) in ("友好", "冷漠")
    ):
        hint = "（需要5GP）" if (
            creature.name == "商人" or getattr(creature, "shop_id", "")
        ) else ""
        options.append(("recruit", f"招募{hint}"))
    if not beast:
        options.append(("ask_quest", "询问委托"))
        giver_quests = [
            quest.name for quest in quests_by_giver(creature.name)
            if quest.name in getattr(state, "active_quests", ())
        ]
        if giver_quests:
            options.append(("deliver_quest", "交付任务"))
    if creature.has_status("睡眠"):
        options.append(("loot", "搜刮"))
    return options
