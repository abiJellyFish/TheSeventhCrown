"""实体工厂：统一实体创建与数据装配入口。"""
from domain.entity.entity import Entity, DEFAULT_STATS
from domain.ports import RepositoryPort, get_repository
from domain.entity.rules import SIZE_RANK, size_rank, stat_adjust, normalize_damage_type
from domain.items.factory import ItemFactory

_GENERIC_ACTIONS_CACHE: list[dict] | None = None


def _generic_actions() -> list[dict]:
    global _GENERIC_ACTIONS_CACHE
    if _GENERIC_ACTIONS_CACHE is None:
        _GENERIC_ACTIONS_CACHE = get_repository().load_actions_data()
    return _GENERIC_ACTIONS_CACHE


class EntityFactory:
    """按职业创建实体；保留数据加载依赖在调用方可注入。"""

    @staticmethod
    def create(name: str, stats: dict | None = None, repository=None) -> Entity:
        return EntityFactory.create_fighter(name, stats or {}, repository)

    @staticmethod
    def from_data(data: dict, repository=None) -> Entity:
        """从已读取的原始实体数据创建实体。"""
        return Entity.from_dict(data, repository=repository)

    @staticmethod
    def create_fighter(name: str, stats: dict | None = None, repository=None) -> Entity:
        return _create_fighter(name, stats or {})

    @staticmethod
    def create_mage(
        name: str,
        stats: dict | None = None,
        domain: str = "evocation",
        repository=None,
    ) -> Entity:
        repo = repository or get_repository()
        class_data = repo.load_class_data("mage") or {}
        return _create_mage(name, stats or {}, domain, class_data, repo)

    @staticmethod
    def fighter(
        name: str,
        stats: dict,
    ) -> Entity:
        return EntityFactory.create_fighter(name, stats)


def _create_fighter(name: str, stats: dict) -> Entity:
    """创建战士。职业/装备由 from_dict 或调用方挂载组件。"""
    s = {**DEFAULT_STATS, **stats}
    s["str"] += 2
    s["con"] += 2
    c = Entity(name=name, faction="守序", hp=35, max_hp=35, max_ap=6, stats=s)
    c.char_class = "fighter"
    c.gp = 3
    return c


_SPELLBOOK_BY_DOMAIN = {"evocation": "法术书_塑能", "abjuration": "法术书_防护"}


def _create_mage(
    name: str,
    stats: dict,
    domain: str = "evocation",
    class_data: dict | None = None,
    repository=None,
) -> Entity:
    """创建魔法使。domain: "evocation" | "abjuration" """
    s = {**DEFAULT_STATS, **stats}
    s["int"] += 2
    spells = {"evocation": ["魔法飞弹"], "abjuration": ["护盾术", "疗伤术"]}
    if class_data is None:
        from domain.spell import load_class_data
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
    # 装备按领域匹配的法术书（2.1：已知法术严格来自已装备法术书）
    book_name = _SPELLBOOK_BY_DOMAIN.get(domain)
    if book_name:
        repo = repository or get_repository()
        book = ItemFactory.create_from_name(book_name, repo)
        if book:
            c.equipment["spellbook"] = book
    return c


