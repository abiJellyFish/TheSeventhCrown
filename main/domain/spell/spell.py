"""法术系统 —— 加载、法术位管理、记忆/替换。"""

from domain.entity import Entity, Weapon
from domain.ports import RepositoryPort, get_repository
from domain.spell.factory import SpellFactory
from domain.damageable import apply_damage

_REPOSITORY = get_repository()
_SPELL_FACTORY = SpellFactory(_REPOSITORY)


def load_spells(repository: RepositoryPort | None = None) -> dict[str, dict]:
    """返回 法术名 → 法术数据 的映射（带缓存）。遍历 data/spells/*.json。"""
    return (SpellFactory(repository or _REPOSITORY)).create_all()


def load_class_data(class_name: str, repository: RepositoryPort | None = None) -> dict | None:
    """返回职业数据（带缓存）。"""
    if not class_name:
        return None
    return (repository or _REPOSITORY).load_class_data(class_name)


def _equipped_spellbook_names(creature: Entity) -> list[str]:
    """返回已装备法术书内记载的法术名列表（无书/未挂载物品栏返回空）。

    用 getattr 读 _inventory 避免在无物品栏的生物上意外挂载组件。
    """
    inv = getattr(creature, "_inventory", None)
    if inv is None:
        return []
    book = inv.equipment.get("spellbook")
    if book is None:
        return []
    return list(getattr(getattr(book, "spellbook", None), "spells", []) or [])


def get_spellbook_spells(creature: Entity) -> list[dict]:
    """返回已装备法术书内可记忆法术的完整数据列表（2.1：严格书源，无书返回空）。"""
    all_spells = load_spells()
    class_data = load_class_data(creature.char_class)
    result = []
    seen = set()
    for name in _equipped_spellbook_names(creature):
        if name in all_spells and name not in seen:
            spell = dict(all_spells[name])
            if class_data:
                dom = spell.get("domain", "")
                spell.setdefault("domain_cn", class_data.get("domains", {}).get(dom, {}).get("name", ""))
            result.append(spell)
            seen.add(name)
    return result


def get_known_spells(creature: Entity) -> list[dict]:
    """返回可记忆法术：严格来自已装备法术书，无书返回空。"""
    return get_spellbook_spells(creature)


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
    """记忆法术到法术位。仅接受已装备法术书内法术；有空位则成功。"""
    if name in creature.memorized_spells:
        return True
    if name not in _equipped_spellbook_names(creature):
        return False
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
    """替换记忆：取消 old，记忆 new（new 须为已装备法术书内法术）。old 未记忆则失败。"""
    if old not in creature.memorized_spells:
        return False
    if new in creature.memorized_spells:
        return False
    if new not in _equipped_spellbook_names(creature):
        return False
    creature.memorized_spells.remove(old)
    creature.memorized_spells.append(new)
    return True


# ═══════════════════════════════════════════════════
# 法术检定与结算
# ═══════════════════════════════════════════════════

def _spell_domain_level(caster: Entity, spell: dict) -> int:
    """获取施法者对应法术领域的等级。"""
    domain_key = spell.get("domain", "")
    from domain.classes import domain_level_for_exp

    return domain_level_for_exp(domain_key, caster.domain_experience.get(domain_key, 0.0))


def spell_attributes(spell: dict) -> list[str]:
    """返回法术施法属性列表。缺省为 ["int"]；单属性/多属性统一为列表。"""
    attr = spell.get("attribute", "int")
    if isinstance(attr, str):
        return [attr]
    return list(attr) if attr else ["int"]


def spell_cast_adjust(caster: Entity, spell: dict, attribute: str | None = None) -> int:
    """施法调整值：按法术属性取调整值。多属性法术按选择取，缺省取第一个。"""
    attrs = spell_attributes(spell)
    attr = attribute if attribute in attrs else attrs[0]
    return caster.stat_adjust(attr)


def spell_mp_cost(caster: Entity, spell: dict) -> int:
    """返回法术精神力消耗；不熟练护甲使消耗翻倍。"""
    base_cost = int(spell.get("mp_cost", 0))
    return base_cost * caster.armor_penalty()["spell_cost_multiplier"]


def spell_save_dc(caster: Entity, spell: dict, attribute: str | None = None) -> int:
    """法术豁免 DC = 8 + 施法属性调整值 + 领域等级（2.2：按法术属性，非职业）。"""
    return 8 + spell_cast_adjust(caster, spell, attribute) + _spell_domain_level(caster, spell)


def spell_saving_throw(target: Entity, dc: int, ability: str = "dex") -> bool:
    """目标进行豁免检定。返回 True = 豁免成功。
    回避状态下敏捷豁免具有优势（阶段7 D19）。"""
    from domain.dice import roll_d20
    adv = 1 if (ability == "dex" and target.has_status("dodge")) else 0
    return (roll_d20(advantage=adv) + target.stat_adjust(ability)) >= dc


def resolve_spell(caster: Entity, target: Entity | None,
                  spell: dict, upcast_level: int = 0, cast_attr: str | None = None) -> dict:
    """结算一次法术施放。target=None 表示空地。cast_attr 为多属性法术选择的施法属性。

    Returns: {"hit": bool, "damage": int, "effect": str, "message": str}
    按 spell["effect"]["type"] 分发：damage / heal / buff。
    """
    from domain.combat.attack import parse_dice, roll_dice
    attrs = spell_attributes(spell)
    caster.grant_attribute_exp(cast_attr if cast_attr in attrs else attrs[0], 0.05)
    domain = spell.get("domain", "")
    if domain:
        caster.grant_domain_exp(domain, 0.05 + 0.01 * spell.get("level", 1))
    level = spell.get("level", 1)
    caster.grant_route_exp("mage", 0.05 + 0.01 * max(0, level - 1))
    result = {"hit": True, "damage": 0, "effect": "", "message": ""}
    effect = spell.get("effect", {})
    etype = effect.get("type", "")
    target_values = target if isinstance(target, list) else [target]
    target_names = [getattr(value, "name", "空地") for value in target_values]
    tname = ", ".join(target_names) if target_values else "空地"

    if etype == "wet_tile":
        result["effect"] = "wet_tile"
        result["message"] = f"{caster.name} 施放了 {spell['name']}，地面变得潮湿"
        return result

    if etype == "damage":
        # 目标模式只决定目标收集方式，不由影响格子数量推断。
        from domain.combat.attack import apply_final_damage, hit_check
        amount = effect.get("amount", "1d4")
        count, sides = parse_dice(amount)
        missiles = effect.get("missiles", 1) + upcast_level  # 升环每阶多制造一支飞弹
        damage_type = effect.get("damage_type", "force")
        needs_hit = bool(spell.get("needs_hit", False))
        save_ability = effect.get("save")
        target_mode = spell.get("target_mode")
        if target_mode not in ("target", "area"):
            target_mode = "target" if not effect.get("area") else "area"
        targets = [value for value in target_values if value is not None]
        if not targets:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
            return result

        weapon = Weapon.from_dict({
            "name": spell["name"],
            "weapon_type": "melee",
            "damage": amount,
            "damage_type": damage_type,
            "attack_stat": spell_attributes(spell)[0],
            "properties": [],
        })
        total = 0
        parts = []
        for current in targets:
            missile_count = missiles if target_mode == "target" else 1
            current_total = 0
            for _ in range(missile_count):
                hit = True
                roll = 10
                is_entity = isinstance(current, Entity)
                if needs_hit and is_entity:
                    hit, roll = hit_check(
                        caster,
                        current,
                        weapon,
                        mod=spell_cast_adjust(caster, spell, cast_attr),
                        guaranteed=bool(spell.get("auto_hit")),
                    )
                if not hit:
                    result["hit"] = False
                    continue
                multiplier = 1
                save_success = None
                if save_ability and is_entity:
                    dc = spell_save_dc(caster, spell, cast_attr)
                    save_success = spell_saving_throw(current, dc, save_ability)
                    multiplier = (
                        0.5
                        if save_success and effect.get("save_half", False)
                        else 1
                    )
                if is_entity:
                    damage_dealt = apply_final_damage(
                        current, int(roll_dice(count, sides) * multiplier),
                        damage_type
                    )
                else:
                    damage_dealt = apply_final_damage(
                        current, int(roll_dice(count, sides) * multiplier),
                        damage_type
                    )
                result["save_success"] = save_success
                current_total += damage_dealt
            if current_total:
                parts.append(f"{current.name}(-{current_total})")
            elif needs_hit:
                parts.append(f"{current.name}(未命中)")
            total += current_total
        result["damage"] = total
        result["message"] = (
            f"对 {', '.join(parts)} 施放 {spell['name']}：共 {total} 点"
            f"{damage_type}伤害"
        )
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
        if isinstance(target, Entity):
            target.heal(healed)
            result["message"] = f"对 {tname} 施放 {spell['name']}：恢复了 {healed} 点生命"
        elif target is not None:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但治疗只能作用于实体"
        else:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
        return result

    if etype == "buff":
        # 增益型（护盾术）：AC+5 全身，承受一次攻击后消失
        result["effect"] = "buff"
        result["message"] = f"{caster.name} 施放了 {spell['name']}，AC+5"
        caster.add_status("shield")  # duration=None 表示持续到承受攻击
        return result

    if etype == "revive":
        if isinstance(target, Entity) and target.is_dead:
            target.revive(hp=1)
            result["effect"] = "revive"
            result["message"] = f"对 {tname} 施放 {spell['name']}：复活"
        else:
            result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
        return result

    if target:
        result["message"] = f"对 {tname} 施放了 {spell['name']}"
    else:
        result["message"] = f"对 {tname} 施放了 {spell['name']}，但没有任何效果"
    return result