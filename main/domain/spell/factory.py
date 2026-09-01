"""法术及职业施法组件工厂。"""

from domain.ports import RepositoryPort, get_repository
from domain.entity import Entity


class SpellFactory:
    """从仓储原始数据创建法术和施法配置。"""

    def __init__(self, repository: RepositoryPort | None = None):
        self.repository = repository or get_repository()

    def create(self, data: dict) -> dict:
        if not isinstance(data, dict) or "name" not in data:
            raise ValueError("法术数据必须包含 name")
        if data.get("effect", {}).get("type") == "damage" and data.get(
            "target_mode"
        ) not in ("target", "area"):
            raise ValueError(f"伤害法术 {data['name']} 必须声明 target_mode")
        return dict(data)

    def create_all(self) -> dict[str, dict]:
        return {
            data["name"]: self.create(data)
            for data in self.repository.load_spell_data().values()
        }

    def class_config(self, class_name: str) -> dict | None:
        return self.repository.load_class_data(class_name)

    def attach_caster(self, creature: Entity, class_name: str, domain: str) -> Entity:
        data = self.class_config(class_name) or {}
        creature.char_class = class_name
        creature.mp = data.get("mp", 100)
        creature.max_mp = data.get("max_mp", 100)
        creature.spell_slots = dict(data.get("spell_slots", {}))
        creature.spell_domains = [domain]
        return creature
