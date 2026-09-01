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
    TALK = auto()        # 交谈
    LOOT = auto()        # 搜刮尸体（旧：直接搜刮，现尸体走 CORPSE 面板）
    CORPSE = auto()      # 尸体面板（搜刮 / 捡起，尸体=每生物武器物品）
    PICK = auto()        # 采摘（灌木）
    REST = auto()        # 休息（床）
    OPEN = auto()        # 开门/关门
    ENTER = auto()       # 进入地城
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

def _detect_creatures(state) -> list[InteractTarget]:
    """检测相邻格生物：活着 → TALK，死亡 → CORPSE（尸体面板：搜刮/捡起）。"""
    pc, pr = state.controlled_entity_pos
    results = []
    for creature, (ec, er) in state.entities:
        if creature.controlled:
            continue
        if max(abs(ec - pc), abs(er - pr)) > 1:
            continue
        if creature.is_dead:
            results.append(InteractTarget(
                label=f"{creature.name}的尸体",
                interact_type=InteractType.CORPSE,
                pos=(ec, er), creature=creature,
            ))
        elif creature.has_status("濒死"):
            results.append(InteractTarget(
                label=f"{creature.name}（濒死）",
                interact_type=InteractType.TALK,
                pos=(ec, er), creature=creature,
                extra={"dying": True},
            ))
        else:
            results.append(InteractTarget(
                label=creature.name,
                interact_type=InteractType.TALK,
                pos=(ec, er), creature=creature,
                extra={},
            ))
    return results


def _detect_doors(state) -> list[InteractTarget]:
    """检测相邻格门。"""
    pc, pr = state.controlled_entity_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            door = next(
                (item for item, item_pos in state.ground_items
                 if item_pos == pos and item.name in ("打开的门", "关闭的门")),
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
    pc, pr = state.controlled_entity_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            if state.map.within_bounds(*pos) and any(
                item_pos == pos and item.name == "床铺"
                for item, item_pos in state.ground_items
            ):
                results.append(InteractTarget(
                    label="床铺", interact_type=InteractType.REST, pos=pos,
                ))
    return results


def _detect_entrances(state) -> list[InteractTarget]:
    """检测自身格及相邻格是否为地城入口/出口。"""
    pc, pr = state.controlled_entity_pos
    results = []
    if not state.in_dungeon:
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (pc + dc, pr + dr)
                if state.map.within_bounds(*pos) and state.map[pos] == Terrain.STAIRS_DOWN:
                    results.append(InteractTarget(
                        label="洞口", interact_type=InteractType.ENTER,
                        pos=pos, extra={"direction": "enter"},
                    ))
    if state.in_dungeon:
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (pc + dc, pr + dr)
                if state.map.within_bounds(*pos) and state.map[pos] == Terrain.STAIRS_UP:
                    results.append(InteractTarget(
                        label="洞口（离开）", interact_type=InteractType.ENTER,
                        pos=pos, extra={"direction": "exit"},
                    ))
    return results


def _detect_ground_items(state) -> list[InteractTarget]:
    """检测玩家所在格及相邻格的地上物品。"""
    from domain.combat.shape import entity_reach
    pc, pr = state.controlled_entity_pos
    reach = entity_reach(state.controlled_entity)
    results = []
    seen: set[tuple[int, int]] = set()
    for item, (ic, ir) in state.ground_items:
        if max(abs(ic - pc), abs(ir - pr)) > reach:
            continue
        pos_key = (ic, ir)
        if pos_key in seen:
            continue
        seen.add(pos_key)
        # 收集该格所有物品信息
        items_at_tile = [it for it, (col, row) in state.ground_items if (col, row) == pos_key]
        if items_at_tile:
            # 显示第一个物品名，堆叠物品显示总数
            total_count = sum(it.count for it in items_at_tile)
            first_item = items_at_tile[0]
            label = "灌木丛" if any("灌木" in it.name for it in items_at_tile) else first_item.name
            if total_count > 1:
                label += f" x{total_count}"
            results.append(InteractTarget(
                label=label, interact_type=InteractType.ITEM,
                pos=pos_key, extra={"items": items_at_tile},
            ))
    return results


def _detect_crops(state) -> list[InteractTarget]:
    """检测相邻格作物：成熟可收获、未成熟可采摘、枯萎可清除。"""
    from domain.crops import crop_label, is_crop_mature, load_seed_config

    pc, pr = state.controlled_entity_pos
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
    _detect_entrances,
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
