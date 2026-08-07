"""JSON 数据加载器 —— 从 test/data/ 加载游戏静态数据。

支持加载生物、物品、法术、AI 规则等 JSON 文件。
"""

import json
import os
from typing import Any

from core.entity import Creature


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

    # ---- 生物 ----

    def load_creature(self, name_or_key: str) -> Creature | None:
        """按名称或 key 加载单个生物。"""
        creatures = self._read("creatures")
        for entry in creatures:
            if entry.get("key") == name_or_key or entry.get("name") == name_or_key:
                return Creature.from_dict(entry)
        return None

    def load_all_creatures(self) -> list[Creature]:
        """加载全部生物。"""
        return [Creature.from_dict(e) for e in self._read("creatures")]

    # ---- 通用 ----

    def load_all(self, category: str) -> list[dict]:
        """加载一个分类的全部条目（返回原始 dict 列表）。"""
        return self._read(category)

    def load_json(self, rel_path: str) -> dict:
        """加载任意 JSON 文件（返回原始 dict）。"""
        return self._read(rel_path)

    # ---- 辅助 ----

    @staticmethod
    def _match_key(entry: dict, name: str) -> bool:
        """用文件名风格的 key 匹配生物名。"""
        key = entry.get("key", "")
        return key == name
