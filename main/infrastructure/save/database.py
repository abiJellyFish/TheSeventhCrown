"""存档系统 —— JSON 持久化存档。

参考: MVP2.md, 修改方案8.md 七、存档系统完善。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from infrastructure.config import SAVE_DIR
from domain.trade import load_item
from domain.element import BurningSurface
from domain.items.item import Item
from domain.obstacle import ObstacleType
from domain.entity.status import StatusEffect
from domain.entity import Entity
from domain.grid import Grid, Terrain
from domain.fov import LightLevel


def _serialize_status(effect) -> dict:
    data = {"name": effect.name, "duration": effect.duration}
    if getattr(effect, "end_event", None):
        data["end_event"] = effect.end_event
    if getattr(effect, "rounds_left", None) is not None:
        data["rounds_left"] = effect.rounds_left
    return data


def _restore_status(entry) -> StatusEffect:
    if not isinstance(entry, dict):
        return StatusEffect(name=entry)
    return StatusEffect(
        name=entry["name"],
        duration=entry.get("duration"),
        end_event=entry.get("end_event"),
        rounds_left=entry.get("rounds_left"),
    )


def _parse_light_source_key(key: str) -> tuple[int, int, int]:
    parts = tuple(map(int, key.split(",")))
    if len(parts) == 3:
        return parts
    raise ValueError("光源坐标必须是三维")


class SaveManager:
    SLOT_NAMES = ("slot_1", "slot_2", "slot_3", "quicksave")

    """存档管理器。使用 SQLite 持久化结构化游戏快照。"""

    def __init__(self, save_dir: str | Path = SAVE_DIR):
        self._dir = save_dir
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        self._db_path = Path(save_dir) / "saves.sqlite3"
        with sqlite3.connect(self._db_path) as conn:
            self._ensure_saves_table(conn)
            conn.execute("DELETE FROM saves WHERE version < 4")

    # ── 保存 ──

    def save(self, state: "GameState", slot: str = "quicksave") -> None:
        """在事务中保存完整游戏状态到指定槽位。"""
        self._validate_slot(slot)
        data = {
            "version": 4,
            "map": {
                "width": state.map.width,
                "height": state.map.height,
                "terrain": [
                    [state.map[col, row].name for col in range(state.map.width)]
                    for row in range(state.map.height)
                ],
            },
            "world_layers": {
                str(z): {
                    "width": layer.width,
                    "height": layer.height,
                    "cells": [
                        [
                            {
                                "terrain": layer.surface((col, row)).terrain.name,
                                "exists": layer.surface((col, row)).exists,
                                "durability": layer.surface((col, row)).durability,
                                "max_durability": layer.surface((col, row)).max_durability,
                            }
                            for col in range(layer.width)
                        ]
                        for row in range(layer.height)
                    ],
                }
                for z, layer in state.world_layers.items()
            },
            "current_map": state.current_map,
            "active_z": state.active_z,
            "controlled_entity_pos": list(state.controlled_entity_pos),
            "controlled_entity": self._serialize_player(state.controlled_entity),
            "controlled_uid": self._entity_ref(state.controlled_entity),
            "party": [member.name for member in getattr(state, "party", [])],
            "entities": self._serialize_entities(
                [(creature, pos) for creature, pos in state.entities
                 if creature is not state.controlled_entity]
            ),
            "clock": {
                "pendulum_count": state.clock.pendulum_count,
                "pendulum_acc_ticks": state.clock.pendulum_acc_ticks,
            },
            "in_combat": state.in_combat,
            "combat_phase": state.combat_phase,
            "current_turn_index": state.current_turn_index,
            "combat_initiative": [self._entity_ref(entity)
                                  for entity in state.combat_initiative],
            "combat_turn_entity": self._entity_ref(state.combat_turn_entity),
            "pending_attack": self._json_safe(state.pending_attack),
            "state_version": state.state_version,
            "slow_mode": state.slow_mode,
            "knockout_mode": state.knockout_mode,
            "observe_mode": state.observe_mode,
            "observe_cursor": list(state.observe_cursor),
            "height_view": getattr(state, "height_view", False),
            "environment_light": (
                state.environment_light.name
                if state.environment_light is not None else None
            ),
            "light_sources": {
                f"{col},{row},{z}": [radius, level.name]
                for (col, row, z), (radius, level) in state.light_sources.items()
            },
            "in_dungeon": state.in_dungeon,
            "ground_items": self._serialize_ground_items(state.ground_items),
            "burning_surfaces": {
                f"{c},{r}": [bs.tier, bs.fuel, bs.tick]
                for (c, r), bs in state.burning_surfaces.items()
            },
            "wet_surfaces": {
                f"{c},{r}": v for (c, r), v in state.wet_surfaces.items()
            },
            "world_state": self._serialize_world_state(state.world_state),
            "map_exits": self._json_safe(state.map_exits),
            "loot_spots": self._json_safe(state.loot_spots),
            "harvested_bushes": self._json_safe(state.harvested_bushes),
            "location_map": {
                f"{col},{row}": value
                for (col, row), value in state.location_map.items()
            },
            "fog_surfaces": [list(pos) for pos in state.fog_surfaces],
            "regen_candidates": [list(pos) for pos in state.regen_candidates],
            "active_quests": list(state.active_quests),
            "completed_quests": list(state.completed_quests),
            "steal_persuade_failures": state.steal_persuade_failures,
            "steal_persuade_bonus": state.steal_persuade_bonus,
            "hidden_from": [
                {"target": target, "observers": list(observers)}
                for target, observers in state.hidden_from.items()
            ],
            "spot_clock": [
                {"observer": observer, "target": target, "clock": clock}
                for (observer, target), clock in state.spot_clock.items()
            ],
            "seen_snap": [
                {"observer": observer, "targets": list(targets)}
                for observer, targets in state.seen_snap.items()
            ],
            "spot_memo": {
                f"{col},{row}": value
                for (col, row), value in state.spot_memo.items()
            },
        }
        if not slot:
            raise ValueError("无效存档槽")
        now = datetime.now().isoformat(timespec="seconds")
        snapshot = json.dumps(data, ensure_ascii=False)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO saves(slot, created_at, updated_at, location,
                character_level, version, snapshot) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET updated_at=excluded.updated_at,
                location=excluded.location, character_level=excluded.character_level,
                version=excluded.version, snapshot=excluded.snapshot""",
                (slot, now, now, state.current_map,
                     0 if state.controlled_entity is None
                     else state.controlled_entity.character_level, 4, snapshot),
            )

    def list_slots(self) -> list[dict]:
        """返回四个存档槽的元数据。"""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT slot, created_at, updated_at, location, character_level "
                "FROM saves ORDER BY slot"
            ).fetchall()
        metadata = {
            row[0]: {"slot": row[0], "created_at": row[1],
                     "updated_at": row[2], "location": row[3],
                     "character_level": None if row[4] is None else int(row[4])}
            for row in rows
        }
        return [
            metadata.get(slot, {"slot": slot, "created_at": None,
                                "updated_at": None, "location": None,
                                "character_level": None})
            for slot in self.SLOT_NAMES
        ]

    @staticmethod
    def _ensure_saves_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS saves (
            slot TEXT PRIMARY KEY, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, location TEXT, character_level INTEGER,
            version INTEGER NOT NULL, snapshot TEXT NOT NULL)"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(saves)")}
        if "player_level" in columns and "character_level" not in columns:
            conn.execute(
                "ALTER TABLE saves RENAME COLUMN player_level TO character_level"
            )

    @classmethod
    def _validate_slot(cls, slot: str) -> None:
        if slot not in cls.SLOT_NAMES:
            raise ValueError(f"无效存档槽: {slot}")

    def delete_slot(self, slot: str, *, confirm: bool = False) -> bool:
        """删除存档槽；必须显式确认，返回是否实际删除。"""
        self._validate_slot(slot)
        if not confirm:
            return False
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM saves WHERE slot=?", (slot,))
            return cursor.rowcount > 0

    # ── 读取 ──

    def load(self, state: "GameState", slot: str = "quicksave",
             loader: "DataLoader | None" = None) -> bool:
        """读取 SQLite 快照并恢复到 GameState。返回是否成功。"""
        self._validate_slot(slot)
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT version, snapshot FROM saves WHERE slot=?", (slot,)
            ).fetchone()
        if row is None:
            return False
        version, snapshot = row
        if version != 4:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM saves WHERE slot=?", (slot,))
            return False
        data = json.loads(snapshot)
        if loader is None:
            from infrastructure.loader import DataLoader
            loader = DataLoader()

        controlled = state.controlled_entity
        if controlled is None:
            raise ValueError("cannot load save without controlled entity")
        controlled_data = data["controlled_entity"]
        self._restore_player(controlled, controlled_data, loader)

        # 恢复位置和地图
        loaded_controlled_pos = tuple(
            data.get("controlled_entity_pos", state.controlled_entity_pos)
        )
        state.active_z = int(data.get("active_z", getattr(state, "active_z", 0)))
        state.height_view = bool(data.get("height_view", False))
        state.controlled_entity_pos = loaded_controlled_pos
        state.current_map = data.get("current_map", state.current_map)
        self._restore_map(state, data.get("map"))
        self._restore_layers(state, data.get("world_layers", {}))
        # 非地表层由分层数据重建二维兼容地图；地表旧快照仍以 map 为准。
        if state.active_z != 0:
            state.set_active_z(state.active_z)
        state.map_exits = data.get("map_exits", [])
        state.loot_spots = data.get("loot_spots", [])
        state.harvested_bushes = {
            tuple(map(int, key.split(","))) if isinstance(key, str) else tuple(key): value
            for key, value in data.get("harvested_bushes", {}).items()
        }
        state.location_map = {
            tuple(map(int, key.split(","))): value
            for key, value in data.get("location_map", {}).items()
        }
        state.fog_surfaces = {tuple(pos) for pos in data.get("fog_surfaces", [])}
        state.regen_candidates = {tuple(pos) for pos in data.get("regen_candidates", [])}
        state.active_quests = list(data.get("active_quests", []))
        state.completed_quests = list(data.get("completed_quests", []))
        state.steal_persuade_failures = data.get("steal_persuade_failures", 0)
        state.steal_persuade_bonus = data.get("steal_persuade_bonus", 0)
        state.hidden_from = {
            int(item["target"]): {int(observer) for observer in item["observers"]}
            for item in data.get("hidden_from", [])
        }
        state.spot_clock = {
            (int(item["observer"]), int(item["target"])): item["clock"]
            for item in data.get("spot_clock", [])
        }
        state.seen_snap = {
            int(item["observer"]): {int(target) for target in item["targets"]}
            for item in data.get("seen_snap", [])
        }
        state.spot_memo = {
            tuple(map(int, key.split(","))): value
            for key, value in data.get("spot_memo", {}).items()
        }
        state.stealth.hidden_from = state.hidden_from
        state.stealth.spot_clock = state.spot_clock
        state.stealth.seen_snap = state.seen_snap
        state.stealth.spot_memo = state.spot_memo

        # 恢复时间
        clock = data.get("clock", {})
        state.clock.pendulum_count = clock.get(
            "pendulum_count", state.clock.pendulum_count
        )
        state.clock.pendulum_acc_ticks = clock.get(
            "pendulum_acc_ticks", state.clock.pendulum_acc_ticks
        )

        # 恢复战斗状态
        state.in_combat = data.get("in_combat", False)
        state.in_dungeon = data.get("in_dungeon", False)
        state.combat_phase = data.get("combat_phase", "idle")
        state.current_turn_index = data.get("current_turn_index", 0)
        state.pending_attack = data.get("pending_attack")
        state.state_version = data.get("state_version", state.state_version)
        state.slow_mode = data.get("slow_mode", state.slow_mode)
        state.knockout_mode = data.get("knockout_mode", state.knockout_mode)
        state.observe_mode = data.get("observe_mode", state.observe_mode)
        state.observe_cursor = tuple(data.get("observe_cursor", state.observe_cursor))

        # 恢复元素地表状态
        state.burning_surfaces = {
            tuple(map(int, k.split(","))): BurningSurface(tier=v[0], fuel=v[1], tick=v[2])
            for k, v in data.get("burning_surfaces", {}).items()
        }
        state.wet_surfaces = {
            tuple(map(int, k.split(","))): v
            for k, v in data.get("wet_surfaces", {}).items()
        }
        saved_light = data.get("environment_light")
        state.environment_light = (
            LightLevel[saved_light] if saved_light else None
        )
        state.light_sources = {
            _parse_light_source_key(key): (value[0], LightLevel[value[1]])
            for key, value in data.get("light_sources", {}).items()
        }

        # 恢复实体（NPC/生物）
        if loader:
            self._restore_entities(state, data.get("entities", []), loader)
        self._restore_ground_items(state, data.get("ground_items", []), loader)
        # 被控生物不在 entities 序列化中，读档后必须重新加入
        player = state.controlled_entity
        if player is not None and not any(c is player for c, _ in state.entities):
            state.entities.append((player, loaded_controlled_pos))

        party_names = data.get("party", [player.name] if player else [])
        by_name = {c.name: c for c, _ in state.entities}
        state.party = [by_name[name] for name in party_names if name in by_name]
        if player is not None and player not in state.party:
            state.party.insert(0, player)
        for member in state.party:
            member.party_member = True
        by_ref = {self._entity_ref(entity): entity for entity, _ in state.entities}
        if player is not None:
            by_ref[self._entity_ref(player)] = player
        state.combat_initiative = [
            by_ref[ref] for ref in data.get("combat_initiative", [])
            if ref in by_ref
        ]
        turn_ref = data.get("combat_turn_entity")
        state.combat_turn_entity = by_ref.get(turn_ref)
        controlled_ref = data.get("controlled_uid")
        saved_controlled = by_ref.get(controlled_ref)
        if saved_controlled is not None and saved_controlled is not state.controlled_entity:
            state.set_controlled(saved_controlled)
        state.pending_attack = self._restore_pending_attack(
            state.pending_attack, by_ref, state
        )

        # 恢复世界状态快照
        ws = data.get("world_state")
        if ws:
            state.world_state = {
                "controlled_entity_pos": tuple(ws["controlled_entity_pos"]),
                "current_map": ws["current_map"],
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
    def _restore_layers(state: "GameState", data: dict) -> None:
        """恢复分层地表及其不可逆破坏状态。"""
        from domain.layers import LayerMap, SurfaceCell
        from domain.grid import Terrain
        for raw_z, payload in data.items():
            layer = LayerMap(payload["width"], payload["height"])
            for row, cells in enumerate(payload["cells"]):
                for col, raw in enumerate(cells):
                    layer.set_surface(
                        (col, row),
                        SurfaceCell(
                            terrain=Terrain[raw["terrain"]],
                            exists=raw["exists"],
                            durability=raw["durability"],
                            max_durability=raw["max_durability"],
                        ),
                    )
            state.world_layers[int(raw_z)] = layer

    @staticmethod
    def _restore_map(state: "GameState", data: dict | None) -> None:
        if not data:
            return
        width = data.get("width", state.map.width)
        height = data.get("height", state.map.height)
        if (width, height) != (state.map.width, state.map.height):
            state.map = Grid[Terrain](width, height, Terrain.GRASS)
            state.map_width = width
            state.map_height = height
        for row, values in enumerate(data.get("terrain", [])):
            for col, terrain_name in enumerate(values):
                state.map[col, row] = Terrain[terrain_name]
        state._terrain_version += 1
        state._transparent_cache = None

    @staticmethod
    def _entity_ref(entity):
        return getattr(entity, "uid", None) if entity is not None else None

    @classmethod
    def _json_safe(cls, value):
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return getattr(value, "uid", getattr(value, "name", str(value)))

    @staticmethod
    def _restore_pending_attack(value, by_ref: dict, state):
        if not isinstance(value, dict):
            return value
        restored = dict(value)
        for key in ("target", "attacker", "actor"):
            ref = restored.get(key)
            if ref in by_ref:
                restored[key] = by_ref[ref]
        weapon_ref = restored.get("weapon")
        if isinstance(weapon_ref, str):
            candidates = []
            for member in state.party:
                candidates.extend(member.inventory)
                candidates.extend(
                    item for item in member.equipment.values() if item is not None
                )
            item = next((item for item in candidates if item.name == weapon_ref), None)
            if item is not None:
                restored["weapon"] = item
        return restored

    @staticmethod
    def _serialize_ground_items(items: list) -> list:
        result = []
        for item, pos in items:
            entry = {
                "name": item.name, "pos": list(pos), "count": item.count,
                "durability": item.durability,
                "max_durability": item.max_durability,
                "door_id": getattr(item, "door_id", ""),
            }
            chest = getattr(item, "chest_data", None)
            if chest is not None:
                entry["chest_data"] = {
                    "label": chest.get("label", "箱子"),
                    "gp": chest.get("gp", 0),
                    "inventory": [
                        {"name": i.name, "count": i.count}
                        for i in chest.get("inventory", [])
                    ],
                }
            result.append(entry)
        return result

    @staticmethod
    def _restore_ground_items(state, data: list, loader) -> None:
        restored = []
        for entry in data:
            item = loader.load_item(entry["name"]) if loader else load_item(entry["name"])
            if item is None:
                item = Item(
                    name=entry["name"],
                    obstacle_type=ObstacleType.NONE,
                    stack_limit=1,
                )
            item.count = entry.get("count", 1)
            item.durability = entry.get("durability", item.durability)
            item.max_durability = entry.get("max_durability", item.max_durability)
            if entry.get("door_id"):
                item.door_id = entry["door_id"]
            chest = entry.get("chest_data")
            if chest is not None:
                inventory = []
                for ref in chest.get("inventory", []):
                    stored = loader.load_item(ref["name"]) if loader else load_item(ref["name"])
                    if stored is not None:
                        stored.count = ref.get("count", 1)
                        inventory.append(stored)
                item.chest_data = {
                    "label": chest.get("label", "箱子"),
                    "gp": chest.get("gp", 0),
                    "inventory": inventory,
                }
            restored.append((item, tuple(entry["pos"]) if len(entry["pos"]) == 3
                             else (*entry["pos"], 0)))
        state.ground_items = restored
        state.invalidate_spatial_cache()

    @staticmethod
    def _serialize_player(player: "Entity") -> dict:
        """将生物序列化为可 JSON 存储的 dict。（Phase 3: Player → Entity）"""
        return {
            "name": player.name,
            "uid": player.uid,
            "char_class": player.char_class,
            "class_level": player.class_level,
            "class_exp": player.class_exp,
            "faction": player.faction,
            "hp": player.hp, "max_hp": player.max_hp,
            "mp": player.mp, "max_mp": player.max_mp,
            "tenacity": player.tenacity, "max_tenacity": player.max_tenacity,
            "attack_streak": getattr(player, "attack_streak", 0),
            "pending_tenacity_bonus": getattr(player, "pending_tenacity_bonus", 0),
            "_tenacity_regen_acc": getattr(player, "_tenacity_regen_acc", 0.0),
            "ap": player.ap, "max_ap": player.max_ap,
            "courage": player.courage, "max_courage": player.max_courage,
            "sanity": player.sanity, "max_sanity": player.max_sanity,
            "mind": player.mind, "max_mind": player.max_mind,
            "exhaustion_level": player.exhaustion_level,
            "starve_pendulums": player.starve_pendulums,
            "body_type": player.body_type,
            "z": player.z,
            "climb_speed": player.climb_speed,
            "fly_speed": player.fly_speed,
            "is_hovering": player.is_hovering,
            "speed": player.speed,
            "stats": dict(player.stats),
            "armor_experience": dict(player.armor_experience),
            "armor_training_progress": dict(player.armor_training_progress),
            "craft_experience": dict(player.craft_experience),
            "tool_experience": dict(player.tool_experience),
            "known_recipes": list(player.known_recipes),
            "recipe_attempts": dict(player.recipe_attempts),
            "gp": player.gp, "sp": player.sp, "cp": player.cp,
            "food_value": player.food_value,
            "food_locked": player.food_locked,
            "vision_range": player.vision_range,
            "darkvision_range": player.darkvision_range,
            "statuses": [_serialize_status(s) for s in player.statuses],
            "equipment": {
                slot: SaveManager._serialize_item(item) if item else None
                for slot, item in player.equipment.items()
            },
            "accessories": [SaveManager._serialize_item(item) for item in player.accessories],
            "inventory": [
                SaveManager._serialize_item(item)
                for item in player.inventory
            ],
            "memorized_spells": list(player.memorized_spells),
            "spell_slots": dict(player.spell_slots),
            "spell_domains": list(player.spell_domains),
            "temp_traits": player.temp_traits,
            "party_member": getattr(player, "party_member", False),
            "attitude": dict(getattr(player, "_attitude", {})),
            "favor": dict(getattr(player, "_favor", {})),
            "_is_dead": getattr(player, "_is_dead", False),
            "_comatose_pendulums": getattr(player, "_comatose_pendulums", 0.0),
            "_death_save_pendulums": getattr(player, "_death_save_pendulums", 0.0),
            "death_saves": (
                None if getattr(player, "death_saves", None) is None else {
                    "successes": player.death_saves.successes,
                    "failures": player.death_saves.failures,
                    "death_injury": player.death_saves.death_injury,
                    "max_hp": player.death_saves.max_hp,
                }
            ),
        }

    @staticmethod
    def _serialize_item(item) -> dict:
        return {
            "name": item.name,
            "count": item.count,
            "durability": item.durability,
            "max_durability": item.max_durability,
            "loaded": item.loaded,
            "quality": getattr(item, "quality", "普通"),
            "unfinished": getattr(item, "unfinished", False),
            "craft_progress": getattr(item, "craft_progress", 0),
            "recipe_id": getattr(item, "recipe_id", ""),
            "craft_tool": getattr(item, "craft_tool", ""),
            "craft_required": getattr(item, "craft_required", 0),
        }

    @staticmethod
    def _serialize_entities(entities: list) -> list:
        """序列化地图上的 NPC/生物。只保存非玩家实体。"""
        result = []
        for creature, position in entities:
            entry = SaveManager._serialize_player(creature)
            entry.update({
                "key": creature.template_name,
                "pos": list(position),
                "statuses": [_serialize_status(s) for s in creature.statuses],
                "_looted": getattr(creature, "_looted", False),
                "loot_rolled": getattr(creature, "loot_rolled", False),
                "loot_drops": [
                    SaveManager._serialize_item(item)
                    for item in getattr(creature, "loot_drops", []) or []
                ],
                "_is_dead": getattr(creature, "_is_dead", False),
                "comatose_pendulums": getattr(creature, "_comatose_pendulums", 0.0),
            })
            result.append(entry)
        return result

    @staticmethod
    def _serialize_world_state(ws: dict | None) -> dict | None:
        """序列化世界状态（地下城进出时保存的地面世界快照）。"""
        if ws is None:
            return None
        return {
            "controlled_entity_pos": list(ws.get("controlled_entity_pos", (0, 0))),
            "current_map": ws.get("current_map", ""),
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
        if data.get("uid") is not None:
            player.uid = data["uid"]
        if data.get("name"):
            player.name = data["name"]
        player.char_class = data.get("char_class", player.char_class)
        player.faction = data.get("faction", player.faction)
        player.z = data.get("z", getattr(player, "z", 0))
        player.climb_speed = data.get("climb_speed", getattr(player, "climb_speed", 0))
        player.fly_speed = data.get("fly_speed", getattr(player, "fly_speed", 0))
        player.is_hovering = data.get("is_hovering", getattr(player, "is_hovering", False))
        player.max_hp = data.get("max_hp", player.max_hp)
        player.hp = data.get("hp", player.hp)
        player.max_mp = data.get("max_mp", player.max_mp)
        player.mp = data.get("mp", player.mp)
        player.max_tenacity = data.get("max_tenacity", player.max_tenacity)
        player.tenacity = data.get("tenacity", player.tenacity)
        player.attack_streak = data.get("attack_streak", 0)
        player.pending_tenacity_bonus = data.get("pending_tenacity_bonus", 0)
        player._tenacity_regen_acc = float(data.get("_tenacity_regen_acc", 0.0))
        player.max_ap = data.get("max_ap", player.max_ap)
        player.ap = data.get("ap", player.ap)
        player.class_level = data.get("class_level", player.class_level)
        player.class_exp = data.get("class_exp", player.class_exp)
        legacy = "sanity" not in data and "max_sanity" not in data
        max_courage = data.get("max_courage", 10)
        courage = data.get("courage", max_courage)
        if legacy and max_courage == 0:
            max_courage = 10
            courage = 10
        player.max_courage = max_courage
        player.courage = min(courage, player.max_courage)
        player.max_sanity = data.get("max_sanity", 100)
        player.sanity = min(data.get("sanity", player.max_sanity), player.max_sanity)
        player.max_mind = data.get("max_mind", 100)
        player.mind = min(data.get("mind", player.max_mind), player.max_mind)
        player.exhaustion_level = data.get("exhaustion_level", 0)
        player.starve_pendulums = float(data.get("starve_pendulums", 0.0))
        player.speed = data.get("speed", 1)
        player.stats = dict(data.get("stats", player.stats))
        player.armor_experience = dict(data.get("armor_experience", {}))
        player.armor_training_progress = dict(data.get("armor_training_progress", {}))
        player.craft_experience = dict(data.get("craft_experience", {}))
        player.tool_experience = dict(data.get("tool_experience", {}))
        player.known_recipes = list(data.get("known_recipes", player.known_recipes))
        player.recipe_attempts = dict(data.get("recipe_attempts", {}))
        player.gp = data.get("gp", 0)
        player.sp = data.get("sp", 0)
        player.cp = data.get("cp", 0)
        player.food_value = data.get("food_value", 15000)
        player.food_locked = data.get("food_locked", False)
        player.statuses = [_restore_status(s) for s in data.get("statuses", [])]
        player.memorized_spells = data.get("memorized_spells", [])
        player.spell_slots = data.get("spell_slots", {})
        player.spell_domains = data.get("spell_domains", [])
        player.temp_traits = data.get("temp_traits", {})
        player._is_dead = data.get("_is_dead", getattr(player, "_is_dead", False))
        player._comatose_pendulums = data.get(
            "_comatose_pendulums", getattr(player, "_comatose_pendulums", 0.0)
        )
        player._death_save_pendulums = data.get(
            "_death_save_pendulums", getattr(player, "_death_save_pendulums", 0.0)
        )
        ds_data = data.get("death_saves")
        if ds_data:
            from domain.death import DeathSaves
            ds = DeathSaves()
            ds.successes = ds_data.get("successes", 0)
            ds.failures = ds_data.get("failures", 0)
            ds.death_injury = ds_data.get("death_injury", 0)
            ds.max_hp = ds_data.get("max_hp", player.max_hp)
            player.death_saves = ds
        player._attitude = dict(data.get("attitude", {}))
        player._favor = {int(k): v for k, v in data.get("favor", {}).items()}

        # 装备重建
        if loader:
            for slot, item_data in data.get("equipment", {}).items():
                item_data = item_data if isinstance(item_data, dict) else {"name": item_data}
                if item_data.get("name") and slot in player.equipment:
                    item = SaveManager._restore_saved_item(item_data, loader)
                    if item:
                        player.equipment[slot] = item
            player.accessories.clear()
            for item_data in data.get("accessories", []):
                item_data = item_data if isinstance(item_data, dict) else {"name": item_data}
                item = SaveManager._restore_saved_item(item_data, loader)
                if item:
                    player.accessories.append(item)
            player.inventory = []
            for entry in data.get("inventory", []):
                item_data = entry if isinstance(entry, dict) else {"name": entry}
                item = SaveManager._restore_saved_item(item_data, loader)
                if item:
                    if item.weight and not item.unfinished:
                        unit = item.weight / max(item.count, 1)
                        item.weight = unit * item.count
                    player.inventory.append(item)

    @staticmethod
    def _overlay_item_craft(item, item_data: dict) -> None:
        if "quality" in item_data:
            item.quality = item_data.get("quality", item.quality)
        item.unfinished = item_data.get("unfinished", False)
        item.craft_progress = item_data.get("craft_progress", 0)
        item.recipe_id = item_data.get("recipe_id", "")
        item.craft_tool = item_data.get("craft_tool", "")
        item.craft_required = item_data.get("craft_required", 0)

    @staticmethod
    def _restore_saved_item(item_data: dict, loader: "DataLoader"):
        if item_data.get("unfinished"):
            from domain.items.item import Item
            item = Item(
                name=item_data["name"],
                unfinished=True,
                recipe_id=item_data.get("recipe_id", ""),
                craft_progress=item_data.get("craft_progress", 0),
                craft_tool=item_data.get("craft_tool", ""),
                craft_required=item_data.get("craft_required", 0),
                count=item_data.get("count", 1),
                durability=item_data.get("durability", 20),
                max_durability=item_data.get("max_durability", 20),
            )
            return item
        item = loader.load_item(item_data.get("name"))
        if item is None:
            return None
        item.count = item_data.get("count", item.count)
        item.durability = item_data.get("durability", item.durability)
        item.max_durability = item_data.get("max_durability", item.max_durability)
        item.loaded = item_data.get("loaded", item.loaded)
        SaveManager._overlay_item_craft(item, item_data)
        return item

    @staticmethod
    def _restore_entities(state: "GameState", data: list,
                          loader: "DataLoader") -> None:
        """从存档数据恢复地图实体。"""
        state.entities = []
        for entry in data:
            c = loader.load_entity(entry["key"])
            if c is None:
                c = Entity(name=entry.get("name", entry.get("key", "未知实体")))
            if c:
                SaveManager._restore_player(c, entry, loader)
                c.faction = entry.get("faction", c.faction)
                c._looted = entry.get("_looted", False)
                c.loot_rolled = entry.get("loot_rolled", False)
                c.loot_drops = []
                for drop in entry.get("loot_drops", []):
                    item = SaveManager._restore_saved_item(drop, loader)
                    if item is not None:
                        c.loot_drops.append(item)
                c._is_dead = entry.get("_is_dead", False)
                c._comatose_pendulums = entry.get("comatose_pendulums", 0.0)
                c.temp_traits = entry.get("temp_traits", {})
                c.party_member = entry.get("party_member", False)
                c.ally = c.party_member
                c._attitude = dict(entry.get("attitude", {}))
                c._favor = {int(k): v for k, v in entry.get("favor", {}).items()}
                state.add_entity(c, tuple(entry["pos"]))
