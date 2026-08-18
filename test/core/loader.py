"""JSON 数据加载器 —— 从 test/data/ 加载游戏静态数据。

支持加载生物、物品、法术、AI 规则等 JSON 文件。
"""

import json
import os
from typing import Any

from core.entity import Entity


class DataLoader:
    """游戏数据加载器。"""

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._cache: dict[str, Any] = {}

    def _read(self, rel_path: str) -> Any:
        """读取 JSON 文件（带缓存）。"""
        if rel_path in self._cache:
            return self._cache[rel_path]
        full = os.path.join(self._data_dir, rel_path + ".json")
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._cache[rel_path] = data
        return data

    # ---- 实体 ----

    def load_entity(self, name: str) -> Entity | None:
        """按中文名加载单个实体（data/entities/{name}.json）。"""
        path = os.path.join(self._data_dir, "entities", f"{name}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Entity.from_dict(data)

    def load_all_entities(self) -> list[Entity]:
        """加载全部实体。"""
        result = []
        for name, data in self.load_all_dir("entities").items():
            result.append(Entity.from_dict(data))
        return result

    # ---- 目录扫描通用工具 ----

    def load_all_dir(self, subdir: str) -> dict[str, dict]:
        """遍历 data/{subdir}/*.json，返回 {文件名: 数据}。文件名即中文 name/key。"""
        d = os.path.join(self._data_dir, subdir)
        result: dict[str, dict] = {}
        if not os.path.isdir(d):
            return result
        for f in sorted(os.listdir(d)):
            if f.endswith(".json"):
                with open(os.path.join(d, f), "r", encoding="utf-8") as fh:
                    result[f[:-5]] = json.load(fh)
        return result

    # ---- 动作 ----

    def load_actions(self) -> list[dict]:
        """加载通用动作集（data/actions.json，单一事实源）。"""
        return self._read("actions")

    # ---- 通用 ----

    def load_all(self, category: str) -> list[dict]:
        """加载一个分类的全部条目（返回原始 dict 列表）。"""
        return self._read(category)

    def load_json(self, rel_path: str) -> dict:
        """加载任意 JSON 文件（返回原始 dict）。"""
        return self._read(rel_path)



DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_DIALOGUES_CACHE: dict | None = None
_SCENE_ACTIONS_CACHE: dict | None = None


def _load_dialogues() -> dict:
    """加载 NPC 对话数据。"""
    global _DIALOGUES_CACHE
    if _DIALOGUES_CACHE is not None:
        return _DIALOGUES_CACHE
    path = os.path.join(DATA_DIR, "dialogues.json")
    with open(path, "r", encoding="utf-8") as f:
        _DIALOGUES_CACHE = json.load(f)
    return _DIALOGUES_CACHE

def _load_scene_actions() -> dict:
    """加载场景描述文本。"""
    global _SCENE_ACTIONS_CACHE
    if _SCENE_ACTIONS_CACHE is not None:
        return _SCENE_ACTIONS_CACHE
    path = os.path.join(DATA_DIR, "scene_actions.json")
    with open(path, "r", encoding="utf-8") as f:
        _SCENE_ACTIONS_CACHE = json.load(f)
    return _SCENE_ACTIONS_CACHE
