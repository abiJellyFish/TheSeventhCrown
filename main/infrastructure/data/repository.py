"""游戏静态数据仓储。

仓储只读取并缓存原始 JSON，不负责创建实体、物品或法术对象。
"""

import json
from pathlib import Path
from typing import Any

from infrastructure.config import DATA_DIR


class DataRepository:
    """按数据领域提供统一的原始数据访问接口。"""

    def __init__(self, data_dir: str | Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._cache: dict[str, Any] = {}

    def _load(self, category: str, key: str) -> dict | None:
        rel = f"{category}/{key}"
        if rel in self._cache:
            return self._cache[rel]
        path = self.data_dir / category / f"{key}.json"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        self._cache[rel] = data
        return data

    def _load_root(self, name: str) -> Any:
        if name in self._cache:
            return self._cache[name]
        path = self.data_dir / f"{name}.json"
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        self._cache[name] = data
        return data

    def _load_category(self, category: str) -> dict[str, dict]:
        directory = self.data_dir / category
        if not directory.is_dir():
            return {}
        return {
            path.stem: self._load(category, path.stem)
            for path in sorted(directory.glob("*.json"))
        }

    def load_entity_data(self, name: str) -> dict | None:
        return self._load("entities", name)

    def load_item_data(self, name: str) -> dict | None:
        return self._load("items", name)

    def load_spell_data(self, name: str | None = None) -> dict | None | dict[str, dict]:
        return self._load_category("spells") if name is None else self._load("spells", name)

    def load_class_data(self, class_name: str) -> dict | None:
        return self._load("classes", class_name)

    def load_shop_data(self, shop_id: str) -> dict | None:
        return self._load("shops", shop_id)

    def save_shop_data(self, shop_id: str, data: dict) -> None:
        path = self.data_dir / "shops" / f"{shop_id}.json"
        original = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as stream:
                original = json.load(stream)
        original.update(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as stream:
            json.dump(original, stream, ensure_ascii=False, indent=2)

    def load_map_data(self, map_name: str) -> dict | None:
        return self._load("maps", map_name)

    def load_actions_data(self) -> list[dict]:
        return self._load_root("actions")

    def load_json(self, relative_path: str) -> Any:
        path = self.data_dir / relative_path
        key = relative_path.removesuffix(".json")
        if key in self._cache:
            return self._cache[key]
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        self._cache[key] = data
        return data

    def load_all(self, category: str) -> dict[str, dict]:
        return self._load_category(category)
