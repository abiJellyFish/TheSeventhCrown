"""存档系统 —— SQLite 增量存档。

MVP 阶段使用内存字典简化实现。
"""

import json
import os
from dataclasses import asdict


class SaveManager:
    """存档管理器（MVP 使用 JSON 文件简化）。"""

    def __init__(self, save_dir: str = "saves"):
        self._dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def save(self, state: "GameState", slot: str = "quicksave") -> None:
        """保存游戏状态。"""
        data = {
            "current_map": state.current_map,
            "player_pos": list(state.player_pos),
            "player": {
                "name": state.player.name,
                "hp": state.player.hp,
                "mp": state.player.mp,
                "tenacity": state.player.tenacity,
                "char_class": state.player.char_class,
            },
            "in_combat": state.in_combat,
        }
        path = os.path.join(self._dir, f"{slot}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, state: "GameState", slot: str = "quicksave") -> bool:
        """读取存档。返回是否成功。"""
        path = os.path.join(self._dir, f"{slot}.json")
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state.current_map = data["current_map"]
        state.player_pos = tuple(data["player_pos"])
        p = data["player"]
        state.player.hp = p["hp"]
        state.player.mp = p["mp"]
        state.player.tenacity = p["tenacity"]
        state.in_combat = data.get("in_combat", False)
        return True
