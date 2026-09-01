"""JSON 数据加载器 —— 从 test/data/ 加载游戏静态数据。

支持加载生物、物品、法术、AI 规则等 JSON 文件。
"""

import json
from pathlib import Path
from typing import Any

from infrastructure.config import DATA_DIR
from domain.entity.factory import EntityFactory
from infrastructure.data.repository import DataRepository
from domain.entity import Entity


class DataLoader(DataRepository):
    """游戏数据加载器。"""

    def __init__(self, data_dir: str | Path = DATA_DIR):
        super().__init__(data_dir)
        self._data_dir = self.data_dir

    def _read(self, rel_path: str) -> Any:
        """读取 JSON 文件（带缓存）。"""
        if rel_path in self._cache:
            return self._cache[rel_path]
        full = self._data_dir / (rel_path + ".json")
        with full.open("r", encoding="utf-8") as f:
            data = json.load(f)
        self._cache[rel_path] = data
        return data

    # ---- 实体 ----

    def load_entity(self, name: str) -> Entity | None:
        """按中文名加载单个实体（data/entities/{name}.json）。"""
        data = self.load_entity_data(name)
        return EntityFactory.from_data(data, self) if data is not None else None

    def load_item(self, name: str):
        """按名称加载物品实例。"""
        from domain.items.factory import ItemFactory
        data = self.load_item_data(name)
        return ItemFactory.create(data) if data is not None else None

    def load_spell(self, name: str) -> dict | None:
        """按名称加载法术原始数据。"""
        return self.load_spell_data(name)

    def load_class_data(self, class_name: str) -> dict | None:
        """加载职业配置。"""
        return super().load_class_data(class_name)

    def load_all_entities(self) -> list[Entity]:
        """加载全部实体。"""
        result = []
        for name, data in self.load_all_dir("entities").items():
            result.append(EntityFactory.from_data(data, self))
        return result

    # ---- 目录扫描通用工具 ----

    def load_all_dir(self, subdir: str) -> dict[str, dict]:
        """遍历 data/{subdir}/*.json，返回 {文件名: 数据}。文件名即中文 name/key。"""
        return super().load_all(subdir)

    # ---- 动作 ----

    def load_actions(self) -> list[dict]:
        """加载通用动作集（data/actions.json，单一事实源）。"""
        return self.load_actions_data()

    # ---- 通用 ----

    def load_all(self, category: str) -> list[dict]:
        """加载一个分类的全部条目（返回原始 dict 列表）。"""
        return list(super().load_all(category).values())

    def load_json(self, rel_path: str) -> dict:
        """加载任意 JSON 文件（返回原始 dict）。"""
        return super().load_json(rel_path + ("" if rel_path.endswith(".json") else ".json"))



_DIALOGUES_CACHE: dict | None = None
_SCENE_ACTIONS_CACHE: dict | None = None


def _load_dialogues() -> dict:
    """加载 NPC 对话数据。"""
    global _DIALOGUES_CACHE
    if _DIALOGUES_CACHE is not None:
        return _DIALOGUES_CACHE
    path = DATA_DIR / "dialogues.json"
    with path.open("r", encoding="utf-8") as f:
        _DIALOGUES_CACHE = json.load(f)
    return _DIALOGUES_CACHE

def _load_scene_actions() -> dict:
    """加载场景描述文本。"""
    global _SCENE_ACTIONS_CACHE
    if _SCENE_ACTIONS_CACHE is not None:
        return _SCENE_ACTIONS_CACHE
    path = DATA_DIR / "scene_actions.json"
    with path.open("r", encoding="utf-8") as f:
        _SCENE_ACTIONS_CACHE = json.load(f)
    return _SCENE_ACTIONS_CACHE
