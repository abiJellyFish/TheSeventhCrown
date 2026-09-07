"""物品栏与选项面板的物品展示文案。空字段跳过，按组件/字段表生成。"""

from domain.trade import price_to_text
from domain.items.item import format_item_type_labels

_DAMAGE_TYPES = {
    "bludgeoning": "钝击",
    "slashing": "挥砍",
    "piercing": "穿刺",
    "fire": "火焰",
    "cold": "寒冷",
    "lightning": "闪电",
    "poison": "毒素",
    "acid": "强酸",
    "radiant": "光耀",
    "necrotic": "黯蚀",
    "force": "力场",
    "psychic": "心灵",
    "thunder": "雷鸣",
}
_WEAPON_TYPES = {"melee": "近战", "ranged": "远程"}
_WEAPON_CATEGORIES = {"simple": "简易", "martial": "制式"}
_ATTACK_STATS = {"str": "力量", "dex": "敏捷", "str_or_dex": "力量或敏捷"}
_ARMOR_TYPES = {
    "clothing": "服饰", "light": "轻甲", "medium": "中甲",
    "heavy": "重甲", "shield": "盾牌",
}
_ARMOR_SLOTS = {
    "head": "头部", "chest": "躯干", "arms": "双臂",
    "legs": "双腿", "full_body": "全身",
}
_LIGHT_LEVELS = {"bright": "明亮", "dim": "微光", "dark": "黑暗"}
_LIGHT_STATES = {"lit": "点燃", "unlit": "未点燃"}
_PROP_NAMES = {
    "light": "轻型", "heavy": "重型", "finesse": "灵巧",
    "two_handed": "双手", "versatile": "两用", "thrown": "投掷",
    "ammunition": "弹药", "loading": "装填", "reach": "触及",
    "ignite_surface": "点燃地表",
}
_EFFECT_NAMES = {
    "heal": "治疗", "restore_mp": "恢复精神", "restore_food": "恢复饮食",
    "start_fire": "点燃", "climb_speed": "攀爬", "fly_speed": "飞行",
    "hover": "悬浮", "revive": "复活",
}


def format_item_detail_lines(item) -> list[str]:
    """玩家可见的物品说明行。无值的字段不输出。"""
    lines: list[str] = []
    for builder in _DETAIL_BUILDERS:
        lines.extend(builder(item))
    return lines


def _kg(value: float) -> str:
    return f"{value:.1f}kg"


def _damage_label(damage_type: str) -> str:
    return _DAMAGE_TYPES.get(damage_type, damage_type)


def _prop_label(prop: str) -> str:
    base, suffix = prop, ""
    if "(" in prop and prop.endswith(")"):
        base, rest = prop.split("(", 1)
        suffix = f"({rest}"
    if base in _PROP_NAMES:
        return _PROP_NAMES[base] + suffix
    if base.startswith("light_") and base[6:].isdigit():
        return f"照明{base[6:]}" + suffix
    return prop


def _count_lines(item) -> list[str]:
    return [f"数量: x{getattr(item, 'count', 1) or 1}"]


def _description_lines(item) -> list[str]:
    desc = getattr(item, "description", "") or ""
    return [f"描述: {desc}"] if desc else []


def _type_lines(item) -> list[str]:
    text = format_item_type_labels(item)
    return [f"类型: {text}"] if text else []


def _weight_lines(item) -> list[str]:
    total = float(getattr(item, "weight", 0) or 0)
    count = getattr(item, "count", 1) or 1
    if count > 1:
        return [f"重量: {_kg(total)}（单件 {_kg(total / count)}）"]
    return [f"重量: {_kg(total)}"]


def _price_lines(item) -> list[str]:
    price = getattr(item, "price", None) or {}
    if not any(price.values()):
        return []
    text = price_to_text(price)
    return [f"价格: {text}"] if text and text != "0CP" else []


def _durability_lines(item) -> list[str]:
    current = getattr(item, "durability", 0)
    maximum = getattr(item, "max_durability", 0)
    if not maximum:
        return []
    show = item.weapon or item.armor or getattr(item, "is_obstacle", False)
    if not show and current == maximum:
        return []
    return [f"耐久: {current}/{maximum}"]


def _weapon_lines(item) -> list[str]:
    weapon = getattr(item, "weapon", None)
    if weapon is None:
        return []
    lines = [
        f"伤害: {weapon.damage} {_damage_label(weapon.damage_type)}",
        f"武器: {_WEAPON_CATEGORIES.get(weapon.category, weapon.category)}"
        f" {_WEAPON_TYPES.get(weapon.weapon_type, weapon.weapon_type)}",
        f"攻击属性: {_ATTACK_STATS.get(weapon.attack_stat, weapon.attack_stat)}",
        f"攻击AP: {weapon.ap_cost}",
    ]
    props = [_prop_label(prop) for prop in (weapon.properties or [])]
    if props:
        lines.append(f"武器属性: {'、'.join(props)}")
    if weapon.range_normal or weapon.range_max:
        lines.append(f"射程: {weapon.range_normal}/{weapon.range_max}")
    if weapon.melee_range:
        lines.append(f"近战触及: {weapon.melee_range}")
    if weapon.special_damage:
        amount = weapon.special_damage.get("amount", "")
        dtype = _damage_label(weapon.special_damage.get("type", ""))
        lines.append(f"额外伤害: {amount} {dtype}".rstrip())
    return lines


def _armor_lines(item) -> list[str]:
    armor = getattr(item, "armor", None)
    if armor is None:
        return []
    lines = [
        f"护甲: {_ARMOR_TYPES.get(item.armor_type, item.armor_type)}"
        f" {_ARMOR_SLOTS.get(item.slot, item.slot)}",
        f"AC: +{item.ac_bonus}",
    ]
    if item.tenacity_bonus:
        lines.append(f"韧性上限增加: {item.tenacity_bonus}")
    if item.str_requirement:
        lines.append(f"力量需求: {item.str_requirement}")
    return lines


def _light_lines(item) -> list[str]:
    light = getattr(item, "light", None)
    if light is None:
        return []
    level = _LIGHT_LEVELS.get(light.level, light.level)
    state = _LIGHT_STATES.get(light.condition, light.condition)
    return [f"光源: 半径{light.radius} {level}（{state}）"]


def _effect_lines(item) -> list[str]:
    effect = getattr(item, "effect", "") or ""
    name = _EFFECT_NAMES.get(effect)
    if not name:
        return []
    amount = getattr(item, "amount", "") or ""
    cost = getattr(item, "ap_cost", 0) or 0
    line = f"效果: {name}"
    if amount:
        line += f" {amount}"
    if cost:
        line += f"  使用AP {cost}"
    return [line]


def _scroll_lines(item) -> list[str]:
    if not getattr(item, "item_type", {}).get("spell_scroll"):
        return []
    lines = []
    spell = getattr(item, "spell", "") or ""
    if spell:
        lines.append(f"法术: {spell}")
    level = getattr(item, "level", 0) or 0
    if level:
        lines.append(f"环阶: {level}")
    cast_time = getattr(item, "cast_time_pendulum", 0) or 0
    if cast_time:
        lines.append(f"施法时间: {cast_time}钟摆")
    range_value = getattr(item, "range", 0) or 0
    if range_value:
        lines.append(f"施法距离: {range_value}")
    if getattr(item, "needs_hit", False):
        lines.append("需要命中")
    return lines


def _spellbook_lines(item) -> list[str]:
    book = getattr(item, "spellbook", None)
    if book is None or not book.spells:
        return []
    return [f"记载法术: {'、'.join(book.spells)}"]


def _throw_lines(item) -> list[str]:
    damage = getattr(item, "throw_damage", "") or ""
    effect = getattr(item, "throw_effect", "") or ""
    str_req = getattr(item, "throw_str_req", 0) or 0
    if not (damage or effect or str_req):
        return []
    parts = [f"投掷距离: {getattr(item, 'throw_range', 3)}"]
    if damage:
        dtype = _damage_label(getattr(item, "throw_damage_type", "") or "")
        parts.append(f"投掷伤害: {damage} {dtype}".rstrip())
    if effect:
        parts.append(f"投掷效果: {effect}")
    if str_req:
        parts.append(f"投掷力量需求: {str_req}")
    return parts


def _trait_lines(item) -> list[str]:
    traits = getattr(item, "traits", None) or []
    return [f"特性: {'、'.join(traits)}"] if traits else []


def _craft_lines(item) -> list[str]:
    if not getattr(item, "unfinished", False):
        return []
    required = getattr(item, "craft_required", 0) or 0
    progress = getattr(item, "craft_progress", 0) or 0
    tool = getattr(item, "craft_tool", "") or ""
    line = f"制作进度: {progress}/{required}" if required else f"制作进度: {progress}"
    if tool:
        line += f"  工具:{tool}"
    return [line]


def _state_lines(item) -> list[str]:
    lines = []
    wet = getattr(item, "wet", 0) or 0
    burning = getattr(item, "burning", 0) or 0
    if wet:
        lines.append(f"潮湿: {wet}")
    if burning:
        lines.append(f"燃烧: {burning}")
    return lines


_DETAIL_BUILDERS = (
    _count_lines,
    _description_lines,
    _type_lines,
    _weight_lines,
    _price_lines,
    _durability_lines,
    _weapon_lines,
    _armor_lines,
    _light_lines,
    _effect_lines,
    _scroll_lines,
    _spellbook_lines,
    _throw_lines,
    _trait_lines,
    _craft_lines,
    _state_lines,
)
