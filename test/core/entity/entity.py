"""实体数据类 —— Entity、Item、Weapon、Armor。

Phase 3: Player 类已删除，统一使用 Entity + controlled 标记。
字段对齐 test/docs/MVP2.md。
"""

from dataclasses import dataclass, field
from typing import Any

from core.ai.components import DEFAULT_BEHAVIOR
from core.items import Item, Weapon, Armor, ITEM_SPACE_DEFAULT
from core.faction import are_hostile, get_attitude, is_ally, FACTION_RELATIONS
from core.entity_factory import (
    size_rank, SIZE_RANK, _generic_actions, _GENERIC_ACTIONS_CACHE,
    stat_adjust, normalize_damage_type, BLUNT_CONVERT,
)
from core.entity_components import (
    ControlComponent, AIComponent, CasterComponent,
    ClassComponent, InventoryComponent,
)
from core.entity.status import StatusEffect


# ═══════════════════════════════════════════════════
# 属性
# ═══════════════════════════════════════════════════

DEFAULT_STATS = {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8}

STAT_NAMES = ["str", "dex", "con", "int", "wis", "cha"]






# ═══════════════════════════════════════════════════
# 状态常量表（沿用字符串，避免魔法值）
# ═══════════════════════════════════════════════════

STATUS_PRONE = "prone"                # 倒地：移动速度减半、攻击劣势、被近战优势/被远程劣势
STATUS_INCAPACITATED = "incapacitated"  # 失能（韧性归零）
STATUS_DYING = "濒死"                  # 濒死：HP=0，进行死亡豁免
STATUS_COMATOSE = "昏迷"               # 昏迷（击晕产物，HP≥1 也可能昏迷）
STATUS_HIDING = "hiding"              # 躲藏：携带锁定对抗值 hide_dc
STATUS_DISENGAGED = "disengaged"      # 已撤离：本回合移动不触发借机攻击
STATUS_DODGE = "dodge"                # 回避中：可见敌人对其攻击劣势、敏捷豁免优势
STATUS_ASSISTED = "assisted"          # 被协助：下一次属性检定优势
STATUS_BURNING = "灼烧"
STATUS_WET = "潮湿"

# 昏迷自然清醒：累积 1500 钟摆后自动清除（期间持续昏迷；失去昏迷后累积清零）
COMATOSE_AUTO_WAKE_PENDULUMS = 1500



# ═══════════════════════════════════════════════════
# Entity
# ═══════════════════════════════════════════════════

@dataclass(init=False)
class Entity:
    """生物数据类（组合模式）。只保留所有生物共有的固有属性，能力域由组件承载。

    字段对齐 MVP2.md 六、生物 定义。
    玩家控制是组件之一（ControlComponent），角色首先是独立实体，玩家选择后挂载控制组件。
    """

    name: str
    faction: str = "中立"                  # "守序" | "中立" | "混乱"
    body_type: str = "humanoid"           # "humanoid" | "beast" | "undead" | ...
    size: str = "medium"                  # "tiny" | "small" | "medium" | "large"（以 MVP2.md 生物定义为准）
    facing: tuple[int, int] = (0, 1)      # 朝向 = DIRS_8 方向向量，默认 (0,1) 东；移动自动转向，手动转向模式可改

    # 核心数值（所有生物共有）
    max_hp: int = 30
    tenacity: int = 10
    max_tenacity: int = 10
    ap: int = 60
    max_ap: int = 60
    speed: int = 1                        # 速度等级 (格子/钟摆)
    ac_base: int = 8                      # 天生 AC（不含敏捷）
    char: str = "?"                       # 地图显示字符（ASCII 单个字符）

    # 属性
    stats: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_STATS))

    # 装备部位 AC 加成
    ac_chest: int = 0
    ac_arms: int = 0
    ac_legs: int = 0
    ac_head: int = 0
    ac_shield: int = 0                    # 全身

    # 其他（所有生物共有）
    vision_range: int = 8
    food_value: int = 15000
    food_locked: bool = False             # True = 饮食值不消耗
    darkvision_range: int = 0             # 0 = 无黑暗视觉
    language: str = ""

    # 动作、特性、掉落（所有生物共有）
    actions: list[dict] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    loot: dict = field(default_factory=dict)
    shop_id: str = ""                     # 商店 id（商人等可交易生物指向 data/shops/{id}.json）

    # 状态效果（所有生物共有）
    statuses: list[StatusEffect] = field(default_factory=list)

    # ── 组件容器（按需挂载，None=未挂载）──
    _control: ControlComponent | None = None
    _ai: AIComponent | None = None
    _caster: CasterComponent | None = None
    _class: ClassComponent | None = None
    _inventory: InventoryComponent | None = None

    # ── HP 属性（死亡系统，D24）──
    # HP 增加（恢复生命）→ 自动清除濒死/昏迷并重置死亡豁免。
    # 所有治疗入口（药水/投掷/休息/疗伤术/食物）都走 hp 赋值，统一接管。

    @property
    def hp(self) -> int:
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        old = getattr(self, "_hp", 0)
        value = max(0, min(int(value), self.max_hp))
        self._hp = value
        # 生命恢复（增加）→ 清除濒死/昏迷（D24：恢复任何生命值即解除）
        if value > old:
            ds = getattr(self, "death_saves", None)
            if ds is not None:
                ds.reset()
            if getattr(self, "statuses", None) is not None:
                self.remove_status(STATUS_DYING)
                self.remove_status(STATUS_COMATOSE)

    @property
    def is_dead(self) -> bool:
        """真正死亡（尸体）。濒死（hp=0）≠ 死亡。"""
        return self._is_dead

    @is_dead.setter
    def is_dead(self, value: bool) -> None:
        self._is_dead = value

    # ── 组件代理属性（业务层无感知访问）──

    # 控制组件
    @property
    def controlled(self) -> bool:
        return self._control is not None and self._control.controlled

    @controlled.setter
    def controlled(self, value: bool) -> None:
        if value:
            if self._control is None:
                self._control = ControlComponent(controlled=True)
            else:
                self._control.controlled = True
        else:
            self._control = None

    # 物品栏组件
    @property
    def inventory(self) -> list:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        return self._inventory.inventory

    @inventory.setter
    def inventory(self, value: list) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.inventory = value

    @property
    def equipment(self) -> dict:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        return self._inventory.equipment

    @equipment.setter
    def equipment(self, value: dict) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.equipment = value

    @property
    def gp(self) -> int:
        return self._inventory.gp if self._inventory else 0

    @gp.setter
    def gp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.gp = value

    @property
    def sp(self) -> int:
        return self._inventory.sp if self._inventory else 0

    @sp.setter
    def sp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.sp = value

    @property
    def cp(self) -> int:
        return self._inventory.cp if self._inventory else 0

    @cp.setter
    def cp(self, value: int) -> None:
        if self._inventory is None:
            self._inventory = InventoryComponent()
        self._inventory.cp = value

    # 职业组件
    @property
    def char_class(self) -> str:
        return self._class.char_class if self._class else ""

    @char_class.setter
    def char_class(self, value: str) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.char_class = value

    @property
    def background(self) -> str:
        return self._class.background if self._class else ""

    @background.setter
    def background(self, value: str) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.background = value

    @property
    def class_level(self) -> float:
        return self._class.class_level if self._class else 0.0

    @class_level.setter
    def class_level(self, value: float) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_level = value

    @property
    def class_exp(self) -> float:
        return self._class.class_exp if self._class else 0.0

    @class_exp.setter
    def class_exp(self, value: float) -> None:
        if self._class is None:
            self._class = ClassComponent()
        self._class.class_exp = value

    # 施法组件
    @property
    def mp(self) -> int:
        return self._caster.mp if self._caster else 0

    @mp.setter
    def mp(self, value: int) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.mp = value

    @property
    def max_mp(self) -> int:
        return self._caster.max_mp if self._caster else 0

    @max_mp.setter
    def max_mp(self, value: int) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.max_mp = value

    @property
    def memorized_spells(self) -> list:
        return self._caster.memorized_spells if self._caster else []

    @memorized_spells.setter
    def memorized_spells(self, value: list) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.memorized_spells = value

    @property
    def spell_slots(self) -> dict:
        return self._caster.spell_slots if self._caster else {}

    @spell_slots.setter
    def spell_slots(self, value: dict) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.spell_slots = value

    @property
    def spell_domains(self) -> list:
        return self._caster.spell_domains if self._caster else []

    @spell_domains.setter
    def spell_domains(self, value: list) -> None:
        if self._caster is None:
            self._caster = CasterComponent()
        self._caster.spell_domains = value

    # AI 组件
    @property
    def behavior_table(self) -> list:
        return self._ai.behavior_table if self._ai else []

    @behavior_table.setter
    def behavior_table(self, value: list) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.behavior_table = value

    @property
    def behavior_overrides(self) -> dict:
        return self._ai.behavior_overrides if self._ai else {}

    @behavior_overrides.setter
    def behavior_overrides(self, value: dict) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.behavior_overrides = value

    @property
    def template_name(self) -> str:
        return self._ai.template_name if self._ai else ""

    @template_name.setter
    def template_name(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.template_name = value

    @property
    def bravery_tier(self) -> str:
        return self._ai.bravery_tier if self._ai else "medium"

    @bravery_tier.setter
    def bravery_tier(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.bravery_tier = value

    @property
    def aggression_tier(self) -> str:
        return self._ai.aggression_tier if self._ai else "medium"

    @aggression_tier.setter
    def aggression_tier(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.aggression_tier = value

    @property
    def schedule(self) -> str:
        return self._ai.schedule if self._ai else "idle"

    @schedule.setter
    def schedule(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.schedule = value

    @property
    def _hunt_target(self) -> Any:
        return self._ai._hunt_target if self._ai else None

    @_hunt_target.setter
    def _hunt_target(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._hunt_target = value

    @property
    def _cached_path(self) -> Any:
        return self._ai._cached_path if self._ai else None

    @_cached_path.setter
    def _cached_path(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._cached_path = value

    @property
    def _path_target(self) -> Any:
        return self._ai._path_target if self._ai else None

    @_path_target.setter
    def _path_target(self, value: Any) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._path_target = value

    @property
    def _action_remaining_cost(self) -> float:
        return self._ai._action_remaining_cost if self._ai else 0.0

    @_action_remaining_cost.setter
    def _action_remaining_cost(self, value: float) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._action_remaining_cost = value

    @property
    def curS_ticks(self) -> int:
        return self._ai.curS_ticks if self._ai else 0

    @curS_ticks.setter
    def curS_ticks(self, value: int) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai.curS_ticks = value

    @property
    def _current_action(self) -> str:
        return self._ai._current_action if self._ai else "idle"

    @_current_action.setter
    def _current_action(self, value: str) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._current_action = value

    @property
    def _ally_count(self) -> int:
        return self._ai._ally_count if self._ai else 0

    @_ally_count.setter
    def _ally_count(self, value: int) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._ally_count = value

    @property
    def _attitude(self) -> dict:
        if self._ai is None:
            self._ai = AIComponent()
        return self._ai._attitude

    @_attitude.setter
    def _attitude(self, value: dict) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._attitude = value

    @property
    def _interrupted(self) -> bool:
        """是否被伤害打断（AI 运行时状态）。"""
        if self._ai is None:
            self._ai = AIComponent()
        return self._ai._interrupted

    @_interrupted.setter
    def _interrupted(self, value: bool) -> None:
        if self._ai is None:
            self._ai = AIComponent()
        self._ai._interrupted = value

    # ---- 状态管理 ----

    def has_status(self, name: str) -> bool:
        """检查是否有指定名称的状态。"""
        return any(s.name == name for s in self.statuses)

    def add_status(self, name: str, duration: int | None = None) -> None:
        """添加状态。若已存在则刷新 duration。"""
        for s in self.statuses:
            if s.name == name:
                if duration is not None:
                    s.duration = duration
                # 失能/不可移动顺带清除回避（阶段7 D19）
                if name in ("incapacitated", "不可移动"):
                    self.remove_status("dodge")
                return
        self.statuses.append(StatusEffect(name=name, duration=duration))
        # 失能/不可移动顺带清除回避（阶段7 D19）
        if name in ("incapacitated", "不可移动"):
            self.remove_status("dodge")
        # 倒地打断当前动作（阶段9：与受伤害打断一致，仅首次进入倒地时触发一次）
        if name == "prone":
            self._interrupted = True
        # 昏迷：进入时重置自然清醒累积（重新累计 1500 钟摆）
        if name == STATUS_COMATOSE:
            self._comatose_pendulums = 0.0

    def remove_status(self, name: str) -> None:
        """移除状态。"""
        self.statuses = [s for s in self.statuses if s.name != name]
        # 失去昏迷 → 清空自然清醒累积（1500 钟摆累计中断）
        if name == STATUS_COMATOSE:
            self._comatose_pendulums = 0.0

    def ignite(self, duration: int) -> None:
        """点燃实体。潮湿状态使灼烧持续时间减半（并消耗潮湿）。"""
        if self.has_status("潮湿"):
            duration = max(1, duration // 2)
            self.remove_status("潮湿")
        self.add_status("灼烧", duration)

    def take_damage(self, amount: int, damage_type: str = "physical", critical: bool = False) -> bool:
        """扣血并标记打断。返回 True 表示触发了打断。

        死亡规则（D24）：
        - 从非 0 降至 0 → 不累积濒死受伤，进入濒死（开始死亡豁免）
        - 已濒死（hp=0）再受伤 → 累积濒死受伤 + 失败计数（重击 +2）
        - 濒死受伤 >= 生命上限 → 立即死亡
        """
        damage_type = normalize_damage_type(damage_type)
        if self._is_dead:
            return False
        if getattr(self, 'controlled', False):
            # 临时：被控生物 HP 保底 1（玩家暂不可死亡，接入完整死亡流程后移除）
            self.hp = max(1, self.hp - amount)
            self._interrupted = True
            return True
        if self.hp <= 0:
            # 已濒死再受伤：累积濒死受伤 + 失败计数
            ds = self._get_death_saves()
            ds.take_damage_at_zero(amount, self.max_hp, critical=critical)
            if ds.death_injury >= self.max_hp:
                self._die()
        elif self.hp - amount <= 0:
            # 从非 0 降至 0 → 进入濒死（不累积濒死受伤）
            self.hp = 0
            self._enter_dying()
        else:
            self.hp -= amount
        self._interrupted = True  # 任何伤害都打断当前动作
        return True

    # ── 死亡系统（D24）──

    def _get_death_saves(self):
        """懒初始化死亡豁免记录。"""
        from core.combat.death import DeathSaves
        if self.death_saves is None:
            self.death_saves = DeathSaves()
            self.death_saves.max_hp = self.max_hp
        return self.death_saves

    def _enter_dying(self):
        """进入濒死：HP=0，开始死亡豁免。陷入濒死会失去昏迷状态。"""
        self.add_status(STATUS_DYING)
        self.remove_status(STATUS_COMATOSE)
        self._get_death_saves().reset()

    def accumulate_comatose(self, delta: float) -> None:
        """昏迷自然清醒累积（1500 钟摆）。仅在持续昏迷时累计；达到阈值自动清除。

        失去昏迷（治疗/濒死/自然清醒）时累积由 remove_status 清空。
        """
        if not self.has_status(STATUS_COMATOSE):
            return
        self._comatose_pendulums += delta
        if self._comatose_pendulums >= COMATOSE_AUTO_WAKE_PENDULUMS:
            self.remove_status(STATUS_COMATOSE)  # remove_status 会清零累积

    def _die(self):
        """真正死亡：置死亡标记，移除濒死/昏迷状态。"""
        self._is_dead = True
        self.remove_status(STATUS_DYING)
        self.remove_status(STATUS_COMATOSE)

    def heal(self, amount: int) -> None:
        """恢复生命。恢复后自动清除濒死/昏迷（由 hp setter 统一处理）。"""
        if self._is_dead:
            return
        self.hp = min(self.max_hp, self.hp + amount)

    def revive(self) -> None:
        """复活（预留）：清死亡标记，HP 恢复为 1。"""
        self._is_dead = False
        self.hp = 1

    def tick_statuses(self) -> list[str]:
        """每钟摆推进状态。灼烧状态每钟摆结算 1d4×倍率 火焰伤害（通过 take_damage）。"""
        from core.combat.attack import roll_dice
        expired = []
        for s in self.statuses:
            if s.duration is not None:
                # 灼烧：本钟摆仍燃烧 → 先结算火焰伤害，再扣计时
                if s.name == "灼烧" and s.duration > 0:
                    fire_traits = self.temp_traits.get("fire", {})
                    burn_mult = fire_traits.get("burn_mult", 1.0)
                    dmg = max(1, int(roll_dice(1, 4) * burn_mult))
                    self.take_damage(dmg, "fire")
                s.duration -= 1
                if s.duration <= 0:
                    expired.append(s.name)
        for name in expired:
            self.remove_status(name)
        return expired

    # ---- AI 字段 ----
    template_name: str = ""               # AI 行为模板名
    bravery_tier: str = "medium"          # "low" | "medium" | "high"
    aggression_tier: str = "medium"       # "low" | "medium" | "high"
    schedule: str = "idle"               # 当前日程

    def meets_condition(self, cond: str) -> bool:
        """检查硬过滤条件。"""
        if cond == "can_move":
            return not self.has_status("incapacitated")
        if cond == "has_weapon":
            return True  # MVP 暂定都有武器
        if cond == "has_healing_potion":
            return False  # MVP NPC 不带药水
        if cond == "enemy_can_communicate":
            return self.language != ""
        return True

    def __init__(
        self,
        name: str,
        faction: str = "中立",
        body_type: str = "humanoid",
        size: str = "medium",
        facing: tuple = (0, 1),
        hp: int = 30,
        max_hp: int = 30,
        tenacity: int = 10,
        max_tenacity: int = 10,
        ap: int = 60,
        max_ap: int = 60,
        speed: int = 1,
        ac_base: int = 8,
        char: str = "?",
        stats: dict | None = None,
        ac_chest: int = 0,
        ac_arms: int = 0,
        ac_legs: int = 0,
        ac_head: int = 0,
        ac_shield: int = 0,
        vision_range: int = 8,
        food_value: int = 15000,
        food_locked: bool = False,
        darkvision_range: int = 0,
        language: str = "",
        actions: list | None = None,
        traits: list | None = None,
        loot: dict | None = None,
        shop_id: str = "",
        corpse: dict | None = None,
        statuses: list | None = None,
        # 组件字段（兼容旧构造方式，通过 property setter 挂载组件）
        controlled: bool = False,
        inventory: list | None = None,
        equipment: dict | None = None,
        gp: int | None = None,
        sp: int | None = None,
        cp: int | None = None,
        char_class: str = "",
        background: str = "",
        class_level: float = 0.0,
        class_exp: float = 0.0,
        mp: int | None = None,
        max_mp: int | None = None,
        memorized_spells: list | None = None,
        spell_slots: dict | None = None,
        spell_domains: list | None = None,
        behavior_table: list | None = None,
        behavior_overrides: dict | None = None,
        template_name: str = "",
        bravery_tier: str = "medium",
        aggression_tier: str = "medium",
        schedule: str = "idle",
        _hunt_target: Any = None,
        _cached_path: Any = None,
        _path_target: Any = None,
        _action_remaining_cost: float = 0.0,
        curS_ticks: int = 0,
        _current_action: str = "idle",
        _ally_count: int = 0,
        _attitude: dict | None = None,
        temp_traits: dict | None = None,
    ):
        # 固有字段（所有生物共有）
        self.name = name
        self.faction = faction
        self.body_type = body_type
        self.size = size
        self.facing = tuple(facing) if facing is not None else (0, 1)
        self._is_dead = False
        self.death_saves = None
        self._comatose_pendulums = 0.0
        self._hp = 0
        self.max_hp = max_hp
        self.hp = hp
        self.tenacity = tenacity
        self.max_tenacity = max_tenacity
        self.ap = ap
        self.max_ap = max_ap
        self.speed = speed
        self.ac_base = ac_base
        self.char = char
        self.stats = dict(stats) if stats else dict(DEFAULT_STATS)
        self.ac_chest = ac_chest
        self.ac_arms = ac_arms
        self.ac_legs = ac_legs
        self.ac_head = ac_head
        self.ac_shield = ac_shield
        self.vision_range = vision_range
        self.food_value = food_value
        self.food_locked = food_locked
        self.darkvision_range = darkvision_range
        self.language = language
        self.actions = actions if actions is not None else []
        self.traits = traits if traits is not None else []
        self.loot = loot if loot is not None else {}
        self.shop_id = shop_id
        # 尸体武器：每生物独立的尸体物品（普通双手武器）。None 表示无尸体。
        self.corpse = Weapon.from_dict(corpse) if corpse else None
        self.statuses = statuses if statuses is not None else []
        self.temp_traits = dict(temp_traits) if temp_traits else {}
        # 组件容器初始化为未挂载
        self._control = None
        self._ai = None
        self._caster = None
        self._class = None
        self._inventory = None
        # 组件字段通过 property setter 挂载（None/默认值表示未挂载）
        if controlled:
            self.controlled = True
        if gp is not None:
            self.gp = gp
        if sp is not None:
            self.sp = sp
        if cp is not None:
            self.cp = cp
        if inventory is not None:
            self.inventory = inventory
        if equipment is not None:
            self.equipment = equipment
        if char_class:
            self.char_class = char_class
        if background:
            self.background = background
        if class_level:
            self.class_level = class_level
        if class_exp:
            self.class_exp = class_exp
        if mp is not None:
            self.mp = mp
        if max_mp is not None:
            self.max_mp = max_mp
        if memorized_spells is not None:
            self.memorized_spells = memorized_spells
        if spell_slots is not None:
            self.spell_slots = spell_slots
        if spell_domains is not None:
            self.spell_domains = spell_domains
        if behavior_table is not None:
            self.behavior_table = behavior_table
        if behavior_overrides is not None:
            self.behavior_overrides = behavior_overrides
        if template_name:
            self.template_name = template_name
        if bravery_tier != "medium":
            self.bravery_tier = bravery_tier
        if aggression_tier != "medium":
            self.aggression_tier = aggression_tier
        if schedule != "idle":
            self.schedule = schedule
        if _hunt_target is not None:
            self._hunt_target = _hunt_target
        if _cached_path is not None:
            self._cached_path = _cached_path
        if _path_target is not None:
            self._path_target = _path_target
        if _action_remaining_cost:
            self._action_remaining_cost = _action_remaining_cost
        if curS_ticks:
            self.curS_ticks = curS_ticks
        if _current_action != "idle":
            self._current_action = _current_action
        if _ally_count:
            self._ally_count = _ally_count
        if _attitude is not None:
            self._attitude = _attitude
        self.__post_init__()

    def __post_init__(self):
        # 钳制 HP/MP/韧性
        self.hp = max(0, min(self.hp, self.max_hp))
        self.tenacity = max(0, min(self.tenacity, self.max_tenacity))

    # ---- 属性 ----

    def stat(self, name: str) -> int:
        return self.stats.get(name, 8)

    def stat_adjust(self, name: str) -> int:
        return stat_adjust(self.stat(name))

    def grant_class_exp(self, amount: float = 0.2) -> bool:
        """命中后累积职业经验，满 1.0 升一级。返回 True 表示本次升级。"""
        if self.class_level >= 2.0:
            return False
        self.class_exp += amount
        if self.class_exp >= 1.0:
            self.class_exp -= 1.0
            self.class_level = min(2.0, self.class_level + 0.2)
            return True
        return False

    # ---- 衍生值 ----

    def initiative_bonus(self) -> int:
        return self.stat_adjust("dex")

    def total_ac(self, body_part: str = "chest") -> int:
        """计算指定部位的总 AC。"""
        base = self.ac_base + self.stat_adjust("dex")
        part_bonus = {
            "chest": self.ac_chest,
            "arms": self.ac_arms,
            "legs": self.ac_legs,
            "head": self.ac_head,
        }.get(body_part, 0)
        # 状态 AC 加成：guarding(+1) / shield(+5 护盾术，全身)
        status_bonus = 0
        if self.has_status("guarding"):
            status_bonus += 1
        if self.has_status("shield"):
            status_bonus += 5
        return base + part_bonus + self.ac_shield + status_bonus

    def carry_capacity(self) -> float:
        """负重上限 (kg) = 20 + 力量调整值 * 2"""
        return 20.0 + self.stat_adjust("str") * 2

    @property
    def total_carry_weight(self) -> float:
        """总负重 = 装备栏 + 物品栏重量之和。"""
        total = 0.0
        for item in self.equipment.values():
            if item is not None:
                total += getattr(item, 'weight', 0.0)
        for item in self.inventory:
            w = getattr(item, 'weight', 0.0)
            count = getattr(item, 'count', 1)
            total += w * count
        return total

    def carry_status(self) -> dict:
        """返回当前负重状态 {threshold, label, effects}。"""
        cap = self.carry_capacity()
        if cap <= 0:
            return CARRY_STATUS["overloaded"]
        ratio = self.total_carry_weight / cap
        if ratio < CARRY_STATUS["light"]["threshold"]:
            return CARRY_STATUS["light"]
        elif ratio < CARRY_STATUS["encumbered"]["threshold"]:
            return CARRY_STATUS["encumbered"]
        else:
            return CARRY_STATUS["overloaded"]

    # ---- 构造 ----

    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        stats = {**DEFAULT_STATS, **data.get("stats", {})}
        creature = cls(
            name=data["name"],
            faction=data.get("faction", "中立"),
            body_type=data.get("body_type", "humanoid"),
            size=data.get("size", "medium"),
            facing=tuple(data.get("facing", (0, 1))),
            hp=data.get("hp", data.get("max_hp", 30)),
            max_hp=data.get("max_hp", data.get("hp", 30)),
            tenacity=data.get("tenacity", 10),
            max_tenacity=data.get("max_tenacity", 10),
            ap=data.get("ap", 6),
            max_ap=data.get("max_ap", 6),
            speed=data.get("speed", 1),
            ac_base=data.get("ac_base", data.get("ac", 8)),
            char=data.get("char") or data.get("key", "?")[0].lower(),
            stats=stats,
            vision_range=data.get("vision_range", 8),
            food_value=data.get("food_value", 15000),
            food_locked=data.get("food_locked", False),
            darkvision_range=data.get("darkvision_range", 0),
            language=data.get("language", ""),
            actions=data.get("actions", []),
            traits=data.get("traits", []),
            loot=data.get("loot", {}),
            shop_id=data.get("shop_id", ""),
            corpse=data.get("corpse"),
            statuses=[StatusEffect(name=s["name"], duration=s.get("duration")) if isinstance(s, dict) else StatusEffect(name=s) for s in data.get("statuses", [])],
            temp_traits=data.get("temperature", {}),
        )

        # 数据驱动挂载组件
        # 1. 物品栏组件（有 inventory 或 equipment 字段则挂载）
        if "inventory" in data or "equipment" in data:
            from core.trade import resolve_items, _load_item_by_key
            inv_comp = InventoryComponent(
                gp=data.get("gp", 0),
                sp=data.get("sp", 0),
                cp=data.get("cp", 0),
            )
            for slot, item_name in data.get("equipment", {}).items():
                if item_name and slot in inv_comp.equipment:
                    item = _load_item_by_key(item_name)
                    if item:
                        inv_comp.equipment[slot] = item
            inv_comp.inventory = resolve_items(data.get("inventory", []))
            creature._inventory = inv_comp

        # 2. 施法组件（有 spell_domains 或 memorized_spells 字段则挂载）
        if "spell_domains" in data or "memorized_spells" in data:
            creature._caster = CasterComponent(
                mp=data.get("mp", 0),
                max_mp=data.get("max_mp", 0),
                memorized_spells=data.get("memorized_spells", []),
                spell_slots=data.get("spell_slots", {}),
                spell_domains=data.get("spell_domains", []),
            )

        # 3. 职业组件（有 char_class 或 class 字段则挂载）
        if "char_class" in data or "class" in data:
            creature._class = ClassComponent(
                char_class=data.get("char_class", data.get("class", "")),
                background=data.get("background", ""),
                class_level=data.get("class_level", 0.0),
                class_exp=data.get("class_exp", 0.0),
            )

        # 4. AI 组件（默认挂载；玩家选中后由 set_controlled 摘除）
        ai_comp = AIComponent()
        behavior = data.get("behavior", None)
        if behavior:
            ai_comp.behavior_table = behavior.get("components", DEFAULT_BEHAVIOR["components"])
            ai_comp.behavior_overrides = behavior.get("overrides", {})
        else:
            ai_comp.behavior_table = list(DEFAULT_BEHAVIOR["components"])
            ai_comp.behavior_overrides = dict(DEFAULT_BEHAVIOR["overrides"])
        creature._ai = ai_comp

        # 5. 合并通用动作（D22：所有实体获得部分动作存入行动表，注入不筛）
        existing_keys = {a.get("key") for a in creature.actions if isinstance(a, dict) and a.get("key")}
        merged = list(creature.actions)
        for ga in _generic_actions():
            if ga.get("key") not in existing_keys:
                merged.append(ga)
        creature.actions = merged

        return creature




# ═══════════════════════════════════════════════════
# 负重状态表（哈希表驱动）
# ═══════════════════════════════════════════════════

CARRY_STATUS = {
    "light":      {"threshold": 0.8,  "label": "轻便",   "effects": []},
    "encumbered": {"threshold": 1.0,  "label": "负重",   "effects": ["speed_halved", "dex_disadvantage", "ap_penalty_1"]},
    "overloaded": {"threshold": float("inf"), "label": "超重", "effects": ["immobilized", "dex_auto_fail", "ap_penalty_2"]},
}




