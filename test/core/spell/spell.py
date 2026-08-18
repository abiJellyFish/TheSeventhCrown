"""法术系统 —— 加载、法术位管理、记忆/替换。"""

import json
import os

from core.entity import Entity

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_SPELL_CACHE: dict[str, dict] | None = None
_CLASS_CACHE: dict[str, dict] = {}


def _load_json(filename: str) -> dict:
    path = os.path.join(_DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_spells() -> dict[str, dict]:
    """返回 法术名 → 法术数据 的映射（带缓存）。遍历 data/spells/*.json。"""
    global _SPELL_CACHE
    if _SPELL_CACHE is None:
        _SPELL_CACHE = {}
        spells_dir = os.path.join(_DATA_DIR, "spells")
        if os.path.isdir(spells_dir):
            for f in sorted(os.listdir(spells_dir)):
                if not f.endswith(".json"):
                    continue
                with open(os.path.join(spells_dir, f), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                _SPELL_CACHE[data["name"]] = data
    return _SPELL_CACHE


def load_class_data(class_name: str) -> dict | None:
    """返回职业数据（带缓存）。"""
    if not class_name:
        return None
    if class_name not in _CLASS_CACHE:
        data = _load_json(f"classes/{class_name}.json")
        _CLASS_CACHE[class_name] = data or {}
    return _CLASS_CACHE.get(class_name) or None


def get_known_spells(creature: Entity) -> list[dict]:
    """返回生物已掌握领域的全部已知法术（来自职业领域配置）。"""
    class_data = load_class_data(creature.char_class)
    if not class_data:
        return []
    all_spells = load_spells()
    domains = getattr(creature, "spell_domains", None) or list(class_data.get("domains", {}).keys())
    result = []
    seen = set()
    for d in domains:
        domain_info = class_data.get("domains", {}).get(d, {})
        for spell_name in domain_info.get("spells", []):
            if spell_name in all_spells and spell_name not in seen:
                spell = dict(all_spells[spell_name])
                spell.setdefault("domain_cn", domain_info.get("name", ""))
                result.append(spell)
                seen.add(spell_name)
    return result


def get_memorized_spells(creature: Entity) -> list[dict]:
    """返回生物已记忆法术的完整数据列表。"""
    all_spells = load_spells()
    result = []
    for name in creature.memorized_spells:
        if name in all_spells:
            result.append(all_spells[name])
    return result


def get_spell_slots(creature: Entity) -> dict[str, int]:
    """返回法术位字典 {"环": 数量}。优先使用生物自身字段，未设置时从职业数据加载。"""
    if getattr(creature, "spell_slots", None):
        return {str(k): int(v) for k, v in creature.spell_slots.items()}
    class_data = load_class_data(creature.char_class)
    if class_data:
        return {str(k): int(v) for k, v in class_data.get("spell_slots", {}).items()}
    return {}


def get_available_slots(creature: Entity) -> int:
    """返回剩余可用法术位数量。"""
    total = sum(get_spell_slots(creature).values())
    return max(0, total - len(creature.memorized_spells))


def memorize_spell(creature: Entity, name: str) -> bool:
    """记忆法术到法术位。有空位则成功，否则返回 False。"""
    if name in creature.memorized_spells:
        return True
    if get_available_slots(creature) <= 0:
        return False
    creature.memorized_spells.append(name)
    return True


def unmemorize_spell(creature: Entity, name: str) -> bool:
    """取消记忆。成功返回 True，未记忆返回 False。"""
    if name not in creature.memorized_spells:
        return False
    creature.memorized_spells.remove(name)
    return True


def replace_spell(creature: Entity, old: str, new: str) -> bool:
    """替换记忆：取消 old，记忆 new。old 未记忆则失败。"""
    if old not in creature.memorized_spells:
        return False
    if new in creature.memorized_spells:
        return False
    creature.memorized_spells.remove(old)
    creature.memorized_spells.append(new)
    return True


# ═══════════════════════════════════════════════════
# 法术检定与结算
# ═══════════════════════════════════════════════════

def _spell_domain_level(caster: Entity, spell: dict) -> int:
    """获取施法者对应法术领域的等级。"""
    class_data = load_class_data(caster.char_class)
    if not class_data:
        return 0
    domain_key = spell.get("domain", "")
    domain_info = class_data.get("domains", {}).get(domain_key, {})
    return domain_info.get("level", 0)


def spell_save_dc(caster: Entity, spell: dict) -> int:
    """法术豁免 DC = 8 + 智力调整值 + 领域等级（MVP2.md：施法豁免属性统一为智力）。"""
    return 8 + caster.stat_adjust("int") + _spell_domain_level(caster, spell)


def spell_saving_throw(target: Entity, dc: int, ability: str = "dex") -> bool:
    """目标进行豁免检定。返回 True = 豁免成功。
    回避状态下敏捷豁免具有优势（阶段7 D19）。"""
    from core.dice import roll_d20
    adv = 1 if (ability == "dex" and target.has_status("dodge")) else 0
    return (roll_d20(advantage=adv) + target.stat_adjust(ability)) >= dc


def resolve_spell(caster: Entity, target: Entity | None,
                  spell: dict, upcast_level: int = 0) -> dict:
    """结算一次法术施放。target=None 表示空地。

    Returns: {"hit": bool, "damage": int, "effect": str, "message": str}
    按 spell["effect"]["type"] 分发：damage / heal / buff。
    """
    from core.combat.attack import parse_dice, roll_dice
    result = {"hit": True, "damage": 0, "effect": "", "message": ""}
    effect = spell.get("effect", {})
    etype = effect.get("type", "")
    tname = target.name if isinstance(target, Entity) else ("空地" if target is None else "")

    if etype == "damage":
        # 伤害型（魔法飞弹）：missiles 颗飞弹 × amount
        from core.combat.attack import hit_check
        amount = effect.get("amount", "1d4")
        count, sides = parse_dice(amount)
        missiles = effect.get("missiles", 1) + upcast_level  # 升环每阶多制造一支飞弹
        # 必定命中（auto_hit）：命中检定未通过时改为刚好成功的点数（通用机制，无特例）
        def _guaranteed_hit(tgt):
            if spell.get("auto_hit") and isinstance(tgt, Entity):
                # 施法攻击调整=智力调整（MVP2.md：施法属性统一为智力）
                hit, roll = hit_check(caster, tgt, mod=caster.stat_adjust("int"), guaranteed=True)
        # 多目标：逐颗飞弹独立掷骰，可分配不同目标
        if isinstance(target, list):
            total = 0
            parts = []
            for t in target:
                _guaranteed_hit(t)
                dmg = roll_dice(count, sides)
                if t:
                    t.take_damage(dmg, "force")
                    parts.append(f"{t.name}(-{dmg})")
                else:
                    parts.append(f"空地(-{dmg})")
                total += dmg
            result["damage"] = total
            result["message"] = f"对 {', '.join(parts)} 施放 {spell['name']}：共 {total} 点力场伤害"
            return result
        # 单目标（所有飞弹打同一目标）
        _guaranteed_hit(target)
        total = sum(roll_dice(count, sides) for _ in range(missiles))
        result["damage"] = total
        if target:
            target.take_damage(total, "force")
            result["message"] = f"对 {tname} 施放 {spell['name']}：{missiles} 颗飞弹造成 {total} 点力场伤害"
        else:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
        return result

    if etype == "heal":
        # 治疗型（疗伤术）：amount + 领域等级
        amount = effect.get("amount", "1d8")
        count, sides = parse_dice(amount)
        healed = roll_dice(count, sides) + _spell_domain_level(caster, spell)
        if upcast_level > 0:
            healed += upcast_level * 8
        result["damage"] = healed
        result["effect"] = "heal"
        if target:
            target.hp = min(target.max_hp, target.hp + healed)
            result["message"] = f"对 {tname} 施放 {spell['name']}：恢复了 {healed} 点生命"
        else:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
        return result

    if etype == "buff":
        # 增益型（护盾术）：AC+5 全身，承受一次攻击后消失
        result["effect"] = "buff"
        result["message"] = f"{caster.name} 施放了 {spell['name']}，AC+5"
        caster.add_status("shield")  # duration=None 表示持续到承受攻击
        return result

    if target:
        result["message"] = f"对 {tname} 施放了 {spell['name']}"
    else:
        result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
    return result