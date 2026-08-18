"""存档系统 —— JSON 持久化存档。

参考: MVP2.md, 修改方案8.md 七、存档系统完善。
"""

import json
import os

from core.trade import _load_item_by_key
from core.element import BurningSurface


class SaveManager:
    """存档管理器。使用 JSON 文件持久化完整游戏状态。"""

    def __init__(self, save_dir: str = "saves"):
        self._dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    # ── 保存 ──

    def save(self, state: "GameState", slot: str = "quicksave") -> None:
        """保存完整游戏状态到 JSON 文件。"""
        data = {
            "version": 1,
            "current_map": state.current_map,
            "player_pos": list(state.player_pos),
            "player": self._serialize_player(state.player),
            "entities": self._serialize_entities(state.entities),
            "clock": {
                "pendulum_count": state.clock.pendulum_count,
                "pendulum_acc_ticks": state.clock.pendulum_acc_ticks,
            },
            "in_combat": state.in_combat,
            "in_dungeon": state.in_dungeon,
            "door_states": {f"{c},{r}": v for (c, r), v in state.door_states.items()},
            "burning_surfaces": {
                f"{c},{r}": [bs.tier, bs.fuel, bs.tick]
                for (c, r), bs in state.burning_surfaces.items()
            },
            "wet_surfaces": {
                f"{c},{r}": v for (c, r), v in state.wet_surfaces.items()
            },
            "world_state": self._serialize_world_state(state.world_state),
        }
        path = os.path.join(self._dir, f"{slot}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 读取 ──

    def load(self, state: "GameState", slot: str = "quicksave",
             loader: "DataLoader | None" = None) -> bool:
        """从 JSON 文件读取存档并恢复到 GameState。返回是否成功。"""
        path = os.path.join(self._dir, f"{slot}.json")
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 恢复玩家
        self._restore_player(state.player, data["player"], loader)

        # 恢复位置和地图
        state.player_pos = tuple(data["player_pos"])
        state.current_map = data["current_map"]

        # 恢复时间
        state.clock.pendulum_count = data["clock"]["pendulum_count"]
        state.clock.pendulum_acc_ticks = data["clock"]["pendulum_acc_ticks"]

        # 恢复战斗状态
        state.in_combat = data.get("in_combat", False)
        state.in_dungeon = data.get("in_dungeon", False)

        # 恢复门
        state.door_states = {
            tuple(map(int, k.split(","))): v
            for k, v in data.get("door_states", {}).items()
        }

        # 恢复元素地表状态
        state.burning_surfaces = {
            tuple(map(int, k.split(","))): BurningSurface(tier=v[0], fuel=v[1], tick=v[2])
            for k, v in data.get("burning_surfaces", {}).items()
        }
        state.wet_surfaces = {
            tuple(map(int, k.split(","))): v
            for k, v in data.get("wet_surfaces", {}).items()
        }

        # 恢复实体（NPC/生物）
        if loader:
            self._restore_entities(state, data.get("entities", []), loader)

        # 恢复世界状态快照
        ws = data.get("world_state")
        if ws:
            state.world_state = {
                "player_pos": tuple(ws["player_pos"]),
                "current_map": ws["current_map"],
                "door_states": {
                    tuple(map(int, k.split(","))): v
                    for k, v in ws.get("door_states", {}).items()
                },
                "burning_surfaces": {
                    tuple(map(int, k.split(","))): BurningSurface(tier=v[0], fuel=v[1], tick=v[2])
                    for k, v in ws.get("burning_surfaces", {}).items()
                },
                "wet_surfaces": {
                    tuple(map(int, k.split(","))): v
                    for k, v in ws.get("wet_surfaces", {}).items()
                },
            }

        return True

    # ── 序列化辅助 ──

    @staticmethod
    def _serialize_player(player: "Entity") -> dict:
        """将生物序列化为可 JSON 存储的 dict。（Phase 3: Player → Entity）"""
        return {
            "name": player.name,
            "char_class": player.char_class,
            "faction": player.faction,
            "hp": player.hp, "max_hp": player.max_hp,
            "mp": player.mp, "max_mp": player.max_mp,
            "tenacity": player.tenacity, "max_tenacity": player.max_tenacity,
            "ap": player.ap, "max_ap": player.max_ap,
            "speed": player.speed,
            "stats": dict(player.stats),
            "gp": player.gp, "sp": player.sp, "cp": player.cp,
            "food_value": player.food_value,
            "food_locked": player.food_locked,
            "vision_range": player.vision_range,
            "darkvision_range": player.darkvision_range,
            "statuses": [{"name": s.name, "duration": s.duration} for s in player.statuses],
            "equipment": {
                slot: item.name if item else None
                for slot, item in player.equipment.items()
            },
            "inventory": [
                {"name": item.name, "count": item.count}
                for item in player.inventory
            ],
            "memorized_spells": list(player.memorized_spells),
            "spell_slots": dict(player.spell_slots),
            "spell_domains": list(player.spell_domains),
            "temp_traits": player.temp_traits,
        }

    @staticmethod
    def _serialize_entities(entities: list) -> list:
        """序列化地图上的 NPC/生物。只保存非玩家实体。"""
        result = []
        for creature, (col, row) in entities:
            ds = getattr(creature, "death_saves", None)
            result.append({
                "key": creature.template_name,
                "pos": [col, row],
                "name": creature.name,
                "faction": creature.faction,
                "hp": creature.hp,
                "mp": creature.mp,
                "tenacity": creature.tenacity,
                "ap": creature.ap,
                "statuses": [{"name": s.name, "duration": s.duration} for s in creature.statuses],
                "food_value": creature.food_value,
                "_looted": getattr(creature, "_looted", False),
                "_is_dead": getattr(creature, "_is_dead", False),
                "comatose_pendulums": getattr(creature, "_comatose_pendulums", 0.0),
                "death_saves": None if ds is None else {
                    "successes": ds.successes,
                    "failures": ds.failures,
                    "death_injury": ds.death_injury,
                    "max_hp": ds.max_hp,
                },
                "temp_traits": creature.temp_traits,
            })
        return result

    @staticmethod
    def _serialize_world_state(ws: dict | None) -> dict | None:
        """序列化世界状态（地下城进出时保存的地面世界快照）。"""
        if ws is None:
            return None
        return {
            "player_pos": list(ws.get("player_pos", (0, 0))),
            "current_map": ws.get("current_map", ""),
            "door_states": {f"{c},{r}": v for (c, r), v in ws.get("door_states", {}).items()},
            "burning_surfaces": {
                f"{c},{r}": [bs.tier, bs.fuel, bs.tick]
                for (c, r), bs in ws.get("burning_surfaces", {}).items()
            },
            "wet_surfaces": {
                f"{c},{r}": v for (c, r), v in ws.get("wet_surfaces", {}).items()
            },
            "entities": SaveManager._serialize_entities(ws.get("entities", [])),
        }

    # ── 恢复辅助 ──

    @staticmethod
    def _restore_player(player: "Entity", data: dict,
                        loader: "DataLoader | None") -> None:
        """从存档数据恢复玩家状态。"""
        player.hp = data["hp"]
        player.max_hp = data["max_hp"]
        player.mp = data["mp"]
        player.max_mp = data["max_mp"]
        player.tenacity = data["tenacity"]
        player.max_tenacity = data["max_tenacity"]
        player.ap = data["ap"]
        player.max_ap = data["max_ap"]
        player.speed = data.get("speed", 1)
        player.stats = data["stats"]
        player.gp = data.get("gp", 0)
        player.sp = data.get("sp", 0)
        player.cp = data.get("cp", 0)
        player.food_value = data.get("food_value", 15000)
        player.food_locked = data.get("food_locked", False)
        player.statuses = [StatusEffect(name=s["name"], duration=s.get("duration")) if isinstance(s, dict) else StatusEffect(name=s) for s in data.get("statuses", [])]
        player.memorized_spells = data.get("memorized_spells", [])
        player.spell_slots = data.get("spell_slots", {})
        player.spell_domains = data.get("spell_domains", [])
        player.temp_traits = data.get("temp_traits", {})

        # 装备重建
        if loader:
            for slot, item_name in data.get("equipment", {}).items():
                if item_name and slot in player.equipment:
                    item = _load_item_by_key(item_name)
                    if item:
                        player.equipment[slot] = item

            # 背包重建
            player.inventory = []
            for entry in data.get("inventory", []):
                item = _load_item_by_key(entry["name"])
                if item:
                    item.count = entry.get("count", 1)
                    if item.weight:
                        item.weight = item.weight * item.count
                    player.inventory.append(item)

    @staticmethod
    def _restore_entities(state: "GameState", data: list,
                          loader: "DataLoader") -> None:
        """从存档数据恢复地图实体。"""
        state.entities = []
        for entry in data:
            c = loader.load_entity(entry["key"])
            if c:
                c.hp = entry.get("hp", c.max_hp)
                c.mp = entry.get("mp", 0)
                c.tenacity = entry.get("tenacity", c.max_tenacity)
                c.ap = entry.get("ap", c.max_ap)
                c.statuses = [StatusEffect(name=s["name"], duration=s.get("duration")) if isinstance(s, dict) else StatusEffect(name=s) for s in entry.get("statuses", [])]
                c.food_value = entry.get("food_value", c.food_value)
                c.faction = entry.get("faction", c.faction)
                c._looted = entry.get("_looted", False)
                c._is_dead = entry.get("_is_dead", False)
                c._comatose_pendulums = entry.get("comatose_pendulums", 0.0)
                ds_data = entry.get("death_saves")
                if ds_data:
                    from core.combat.death import DeathSaves
                    ds = DeathSaves()
                    ds.successes = ds_data.get("successes", 0)
                    ds.failures = ds_data.get("failures", 0)
                    ds.death_injury = ds_data.get("death_injury", 0)
                    ds.max_hp = ds_data.get("max_hp", c.max_hp)
                    c.death_saves = ds
                c.temp_traits = entry.get("temp_traits", {})
                state.add_entity(c, tuple(entry["pos"]))
