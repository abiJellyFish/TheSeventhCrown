"""通用交互系统 —— 可交互目标检测、交互类型定义、哈希表分发。

新增交互目标类型：
  1. 写一个 _detect_xxx(state) → list[InteractTarget]
  2. 追加到 _DETECTORS 列表
  3. 在 app.py 的 _INTERACT_DISPATCH 加一行

新增生物 trait 标记：
  在 CREATURE_TRAIT_FLAGS 加一行即可。
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from core.grid import DIRS_8
from core.movement import Terrain


class InteractType(Enum):
    TALK = auto()        # 交谈
    LOOT = auto()        # 搜刮尸体（旧：直接搜刮，现尸体走 CORPSE 面板）
    CORPSE = auto()      # 尸体面板（搜刮 / 捡起，尸体=每生物武器物品）
    PICK = auto()        # 采摘（灌木）
    REST = auto()        # 休息（床）
    OPEN = auto()        # 开门/关门
    ENTER = auto()       # 进入地城
    PICKUP = auto()      # 捡起地上物品
    CHEST = auto()       # 箱子
    FETCH_WATER = auto() # 取水（空玻璃瓶 → 一瓶水）


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

CREATURE_TRAIT_FLAGS: dict[str, str] = {
    "merchant": "can_trade",
}


# ═══════════════════════════════════════════════════
# 检测器（新增可交互类型只需追加函数到 _DETECTORS）
# ═══════════════════════════════════════════════════

def _detect_creatures(state) -> list[InteractTarget]:
    """检测相邻格生物：活着 → TALK，死亡 → CORPSE（尸体面板：搜刮/捡起）。"""
    pc, pr = state.player_pos
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
            flags = {}
            for trait in getattr(creature, 'traits', []) or []:
                if trait in CREATURE_TRAIT_FLAGS:
                    flags[CREATURE_TRAIT_FLAGS[trait]] = True
            results.append(InteractTarget(
                label=creature.name,
                interact_type=InteractType.TALK,
                pos=(ec, er), creature=creature,
                extra=flags,
            ))
    return results


def _detect_doors(state) -> list[InteractTarget]:
    """检测相邻格门。"""
    pc, pr = state.player_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            if pos in state.door_states:
                label = "打开的门" if state.door_states[pos] else "关闭的门"
                results.append(InteractTarget(
                    label=label, interact_type=InteractType.OPEN,
                    pos=pos, extra={"is_open": state.door_states[pos]},
                ))
    return results


def _detect_beds(state) -> list[InteractTarget]:
    """检测相邻格床。"""
    pc, pr = state.player_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            pos = (pc + dc, pr + dr)
            if state.map.within_bounds(*pos) and state.map[pos] == Terrain.BED:
                results.append(InteractTarget(
                    label="床铺", interact_type=InteractType.REST, pos=pos,
                ))
    return results


def _detect_bushes(state) -> list[InteractTarget]:
    """检测相邻格灌木（可采摘浆果，排除石头）。"""
    pc, pr = state.player_pos
    results = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            nc, nr = pc + dc, pr + dr
            if not state.map.within_bounds(nc, nr):
                continue
            if state.map[nc, nr] == Terrain.BUSH:
                results.append(InteractTarget(
                    label="灌木丛", interact_type=InteractType.PICK, pos=(nc, nr),
                ))
    return results


def _detect_entrances(state) -> list[InteractTarget]:
    """检测自身格及相邻格是否为地城入口/出口。"""
    pc, pr = state.player_pos
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


def _detect_chests(state) -> list[InteractTarget]:
    """检测相邻格箱子。"""
    pc, pr = state.player_pos
    results = []
    for (cx, cy), chest_data in state.chests.items():
        if max(abs(cx - pc), abs(cy - pr)) <= 1:
            results.append(InteractTarget(
                label=chest_data.get("label", "箱子"),
                interact_type=InteractType.CHEST,
                pos=(cx, cy),
                extra={"chest_data": chest_data},
            ))
    return results


def _detect_ground_items(state) -> list[InteractTarget]:
    """检测玩家所在格及相邻格的地上物品。"""
    pc, pr = state.player_pos
    results = []
    seen: set[tuple[int, int]] = set()
    for item, (ic, ir) in state.ground_items:
        if max(abs(ic - pc), abs(ir - pr)) > 1:
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
            label = f"{first_item.name}"
            if total_count > 1:
                label += f" x{total_count}"
            results.append(InteractTarget(
                label=label, interact_type=InteractType.PICKUP,
                pos=pos_key, extra={"items": items_at_tile},
            ))
    return results


def _detect_water(state) -> list[InteractTarget]:
    """检测玩家相邻的水源地块（WATER 地形），需背包有空玻璃瓶。"""
    targets = []
    if not state.player:
        return targets
    pc, pr = state.player_pos
    # 检查背包是否有空玻璃瓶
    has_bottle = any(
        item.name == "空玻璃瓶" and item.count > 0
        for item in state.player.inventory
    )
    if not has_bottle:
        return targets
    # 扫描相邻 8 格
    for dc, dr in DIRS_8:
        pos = (pc + dc, pr + dr)
        if state.map.within_bounds(*pos) and state.map[pos] == Terrain.WATER:
            targets.append(InteractTarget(
                label="取水",
                interact_type=InteractType.FETCH_WATER,
                pos=pos,
            ))
    return targets


# 检测器注册列表（新增目标类型只需追加函数）
_DETECTORS: list = [
    _detect_doors,
    _detect_entrances,
    _detect_chests,
    _detect_beds,
    _detect_creatures,
    _detect_bushes,
    _detect_ground_items,
    _detect_water,
]


def scan_interact_targets(state) -> list[InteractTarget]:
    """扫描玩家周围可交互目标。遍历所有检测器，聚合结果。"""
    targets = []
    for detector in _DETECTORS:
        targets.extend(detector(state))
    return targets
