"""委托系统（P1 3.4）—— 任务加载、哈希表查找、交付条件。

每个任务单独一份文件（data/quests/*.json），按任务名与委托人建立索引。
接取后任务状态存于 GameState（active_quests / completed_quests）。
"""
import json
import os
from dataclasses import dataclass


_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "quests")

_quest_cache: dict[str, "Quest"] | None = None


@dataclass(frozen=True)
class Quest:
    """任务定义。报酬写在 reward_text（描述文本），发放物品/金币走 reward_* 字段。"""
    name: str
    giver: str
    description: str
    reward_text: str = ""
    complete_items: tuple[str, ...] = ()   # 完成条件：需背包持有的物品名
    reward_items: tuple[str, ...] = ()     # 交付发放的物品名
    reward_gp: int = 0                     # 交付发放的金币


def load_quests() -> dict[str, Quest]:
    """加载所有任务文件，返回 {任务名 → Quest} 哈希表。"""
    global _quest_cache
    if _quest_cache is None:
        quests = {}
        if os.path.isdir(_DATA_DIR):
            for fname in os.listdir(_DATA_DIR):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(_DATA_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                quests[data["name"]] = Quest(
                    name=data["name"],
                    giver=data.get("giver", ""),
                    description=data.get("description", ""),
                    reward_text=data.get("reward_text", ""),
                    complete_items=tuple(data.get("complete_items", [])),
                    reward_items=tuple(data.get("reward_items", [])),
                    reward_gp=data.get("reward_gp", 0),
                )
        _quest_cache = quests
    return _quest_cache


def quests_by_giver(giver_name: str) -> list[Quest]:
    """按委托人查找任务（哈希表 O(1) 聚合）。"""
    return [q for q in load_quests().values() if q.giver == giver_name]


def can_complete(player, quest: Quest) -> bool:
    """完成条件：任务物品均在玩家背包中。"""
    inv_names = {i.name for i in player.inventory}
    return all(name in inv_names for name in quest.complete_items)


def complete_quest(player, quest: Quest) -> bool:
    """交付任务：移除任务物品、发放奖励物品与金币。返回是否成功。"""
    if not can_complete(player, quest):
        return False
    # 移除任务物品（每个名称移除 1 件，支持堆叠）
    for name in quest.complete_items:
        for i, it in enumerate(player.inventory):
            if it.name == name:
                if it.count > 1:
                    it.count -= 1
                else:
                    player.inventory.pop(i)
                break
    # 发放奖励物品
    from domain.trade import load_item
    for name in quest.reward_items:
        item = load_item(name)
        if item is not None:
            player.inventory.append(item)
    player.gp += quest.reward_gp
    return True
