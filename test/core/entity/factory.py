"""实体工厂 —— create_fighter / create_mage。"""
from core.entity.entity import Entity, DEFAULT_STATS


def create_fighter(name: str, stats: dict) -> Entity:
    """创建战士。职业/装备由 from_dict 或调用方挂载组件。"""
    s = {**DEFAULT_STATS, **stats}
    s["str"] += 2
    s["con"] += 2
    c = Entity(name=name, faction="守序", hp=35, max_hp=35, max_ap=6, stats=s)
    c.char_class = "fighter"
    c.gp = 3
    return c


def create_mage(name: str, stats: dict, domain: str = "evocation") -> Entity:
    """创建魔法使。domain: "evocation" | "abjuration" """
    s = {**DEFAULT_STATS, **stats}
    s["int"] += 2
    spells = {"evocation": ["魔法飞弹"], "abjuration": ["护盾术", "疗伤术"]}
    from core.spell import load_class_data
    class_data = load_class_data("mage") or {}
    slots = dict(class_data.get("spell_slots", {}))
    c = Entity(name=name, faction="守序", hp=30, max_hp=30, max_ap=6, stats=s)
    c.char_class = "mage"
    c.gp = 3
    c.mp = 100
    c.max_mp = 100
    c.memorized_spells = spells.get(domain, [])
    c.spell_slots = slots
    c.spell_domains = [domain]
    return c
