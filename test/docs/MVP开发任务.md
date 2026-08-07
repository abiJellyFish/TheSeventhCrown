# MVP 开发任务

> **目标：** 搭出可运行的最小原型——创建角色、探索村庄、接任务、战斗、完成地城。
>
> **原则：** TDD（先写测试再写代码）、模块化（core/render 分离）、数据驱动（JSON 配置）。
>
> **参考文档：** `../方案4.md`（规则）、`../MVP2.md`（MVP 数据集）、`../补充1.md`（AI & 渲染方案）、`../速度机制2.md`（时间系统）。
>
> **所有文件放在 `test/` 目录内。**

---

## 全局约束

- Python >= 3.12
- 依赖：`textual`（渲染）、`pytest`（测试），无其他第三方库
- 地图格只使用 ASCII 95 可打印字符（码点 32–126）
- 中文文本只在日志/面板的 Rich 组件中使用
- 数值不硬编码，从 JSON 加载
- `core/` 不得 import 任何渲染库
- 每个模块先写测试，再写实现

### MVP 阶段暂不实现

以下规则在方案4.md 中有定义，但 MVP 阶段跳过，后续迭代再加入：

| 跳过的功能 | 原因 | MVP 简化方案 |
|-----------|------|-------------|
| 反应动作 / 借机攻击 / 准备动作 | 需要完整的反应窗口系统 | 护盾术按普通动作施放（非反应），不触发借机攻击 |
| 双持/双手并用的 AP 计算 | 需要武器组合判定逻辑 | 只做单手攻击，双持数据留接口 |
| 生物朝向（身前/身后/身侧） | MVP 无朝向相关技能 | 暂不记录朝向 |
| 完整日程系统（NPC 按时间表活动） | 复杂度高 | NPC 只响应战斗 AI，探索模式下原地待机 |
| 升环施法 | MVP 只有一环法术位 | 法术数据保留升环字段，逻辑暂不实现 |
| 护甲熟练项惩罚 | MVP 生物/玩家没有不熟练的装备 | 假定所有装备均有熟练 |
| 法术 DC / 法术豁免检定 | MVP 法术均为必定命中或自我施法 | 法术数据保留 DC 字段 |
| 完整温度系统（热源/传播/元素反应） | 闭环太长 | 只做篝火和火把的地表效果标记，不做温度传播 |
| 报纸、据点、声望、制作/锻造/炼金 | 非核心循环 | 跳过 |
| 盟友招募 | MVP 只有玩家单人 | 数据层预留队伍槽位 |
| 生物捕猎/采集 AI | 复杂度高 | 生物饮食值锁定，只随机游荡，预留捕猎/采集接口 |

> MVP 聚焦目标：**能创建角色 → 能走地图 → 能战斗 → 能完成任务**。其他系统保证数据的结构和接口预留，逻辑后续迭代。

---

## 模块总览

```
test/
├── MVP开发任务.md
├── requirements.txt
├── core/                    # 游戏逻辑（零渲染依赖）
│   ├── dice.py              # 骰子 / 优势劣势
│   ├── grid.py              # 泛型网格 Grid[T]
│   ├── entity.py            # Entity / Creature / Item / Player 数据类
│   ├── game_state.py        # GameState 全局状态
│   ├── movement.py          # 移动合法性 / A* 寻路
│   ├── fov.py               # 递归阴影投射视野 + 光照等级
│   ├── pendulum.py          # 钟摆时间系统 + 定时事件
│   ├── rest.py              # 短休/长休 + 舒适加成
│   ├── combat/              # 战斗子系统
│   │   ├── initiative.py    # 先攻排序
│   │   ├── attack.py        # 命中 / 伤害 / 重击 / 伤害类型 / 抗性易伤
│   │   ├── cover.py         # 掩体结算（射线检测 + 掩体 AC）
│   │   └── death.py         # 死亡豁免 / 濒死受伤
│   ├── ai/                  # AI 子系统
│   │   ├── discretize.py    # 状态离散化
│   │   ├── engine.py        # 决策引擎（查表 + Counter）
│   │   └── loader.py        # JSON 加载 + 预乘权重
│   ├── map/                 # 地图子系统
│   │   └── generation/      # 地图生成
│   │       └── bsp.py       # BSP 地城生成
│   ├── save/                # 存档子系统
│   │   └── database.py      # SQLite 增量存档
│   └── loader.py            # 通用 JSON 数据加载器
├── data/                    # 静态 JSON 数据（从 MVP2.md 提取）
│   ├── creatures/
│   ├── items/
│   ├── spells/
│   ├── ai/
│   ├── classes/
│   └── maps/
├── render/                  # 渲染层
│   ├── renderer.py          # Renderer 抽象接口
│   ├── animation.py         # AnimationDef 数据类
│   └── textual/             # Textual 实现
│       ├── app.py
│       ├── screens/
│       ├── widgets/
│       └── layers/
└── tests/                   # pytest 测试
    ├── test_dice.py
    ├── test_grid.py
    ├── test_movement.py
    ├── test_fov.py
    ├── test_combat.py
    ├── test_ai.py
    ├── test_pendulum.py
    ├── test_rest.py
    └── test_entity.py
```

---

## 阶段 0：项目骨架

### 模块 0.1 — 环境搭建

**目标：** 创建目录结构、`requirements.txt`、确认 textual 和 pytest 可导入。

**文件：**
- `test/requirements.txt`
- `test/core/__init__.py`
- `test/core/combat/__init__.py`
- `test/core/ai/__init__.py`
- `test/render/__init__.py`
- `test/render/textual/__init__.py`
- `test/data/`（空目录 + 占位）
- `test/tests/__init__.py`

**验收：** `pytest --version` 正常；`python -c "import textual"` 正常。

**任务步骤：**

- [ ] 0.1.1 创建 `test/` 下全部目录结构
- [ ] 0.1.2 编写 `requirements.txt`（`textual`、`pytest`）
- [ ] 0.1.3 `pip install -r requirements.txt`，验证导入
- [ ] 0.1.4 提交 commit

---

## 阶段 1：数据层

### 模块 1.1 — 骰子系统

**目标：** 实现 D20 骰子池（优势劣势可叠加/抵消）、`2d6`、向下取整。

**参考：** 方案4.md 规则部分。优势：额外多掷一颗骰子，任选一颗作为结果，多个优势可叠加。劣势：移除一颗骰子，最低剩余一颗。优势劣势并存时先抵消再计算骰子数。

**验收：** 基础 D20 范围 1–20；优势+N 多掷 N 颗取最高；劣势-N 少掷 N 颗（最低 1 颗）；优势劣势可抵消；2d6 范围 2–12。

**文件：**
- `test/core/dice.py`
- `test/tests/test_dice.py`

**任务步骤：**

- [ ] 1.1.1 写 `test_roll_d20_range` — 基础 D20 范围 1–20
- [ ] 1.1.2 实现 `roll_d20()` → 验证测试通过
- [ ] 1.1.3 写 `test_advantage_adds_extra_die` — 优势=1 时多掷 1 颗（共 2 颗），任选结果（取最高）
- [ ] 1.1.4 实现 `roll_d20(advantage=1)` → 验证测试通过
- [ ] 1.1.5 写 `test_disadvantage_removes_die` — 劣势=1 时移除 1 颗（还剩 1 颗），效果等同于正常 D20
- [ ] 1.1.6 写 `test_advantage_disadvantage_cancel` — 优势=1 劣势=1 互相抵消（骰子数 = 1+1-1 = 1）
- [ ] 1.1.7 写 `test_multiple_advantage_stack` — 优势=3 时多掷 3 颗（共 4 颗），取最高
- [ ] 1.1.8 写 `test_disadvantage_minimum_one_die` — 劣势=5 时骰子数 = max(1+0-5, 1) = 1，不会降到 0
- [ ] 1.1.9 实现完整的 `roll_d20(advantage=0, disadvantage=0)` 骰子池逻辑 → 验证全部测试通过
- [ ] 1.1.10 写 `test_roll_2d6_range` — 2d6 范围 2–12
- [ ] 1.1.11 实现 `roll_2d6()` → 验证测试通过
- [ ] 1.1.12 写 `test_check_dc` — D20 + 调整值 vs DC，>= 为成功
- [ ] 1.1.13 实现 `check_dc(adjust, dc)` → 验证测试通过
- [ ] 1.1.14 提交 commit

### 模块 1.2 — 泛型网格

**目标：** `Grid[T]`，支持 `get/set/within_bounds`，坐标用 `(col, row)`。

**验收：** 创建 10×10 Grid，get/set 值正确，越界返回 None。

**文件：**
- `test/core/grid.py`
- `test/tests/test_grid.py`

**任务步骤：**

- [ ] 1.2.1 写 `test_grid_create_and_access` — 创建网格，set/get
- [ ] 1.2.2 实现 `Grid` 类 → 验证测试通过
- [ ] 1.2.3 写 `test_grid_out_of_bounds` — 越界返回 None
- [ ] 1.2.4 写 `test_grid_neighbors` — 获取 8 方向邻居坐标
- [ ] 1.2.5 实现 `neighbors()` → 验证测试通过
- [ ] 1.2.6 提交 commit

### 模块 1.3 — 实体数据类

**目标：** `Entity` 基类、`Creature`、`Item`、`Player` 数据类。字段对齐 MVP2.md。

**参考：** MVP2.md 生物/物品/武器/护甲数据。

**验收：** 从 Creature 字典构造实例，属性正确加载；HP/MP/AP 和装备部位。

**文件：**
- `test/core/entity.py`
- `test/tests/test_entity.py`

**任务步骤：**

- [ ] 1.3.1 写 `test_creature_from_dict` — 用地精打手数据构造 Creature
- [ ] 1.3.2 实现 `Creature` 数据类 → 验证测试通过
- [ ] 1.3.3 写 `test_player_creation` — 人类战士初始属性
- [ ] 1.3.4 实现 `Player`（继承 Creature）→ 验证测试通过
- [ ] 1.3.5 实现 `Item`、`Weapon`、`Armor` 数据类（不需要独立测试，验证在前面的测试中）
- [ ] 1.3.6 `Creature` 预留字段：`ally_slot`（null = 未入队）、`food_locked`（True = 饮食值不消耗）、`darkvision_range`（0 = 无黑暗视觉）
- [ ] 1.3.7 `Player` 预留 `party: list[Creature]`（队伍槽位，MVP 暂为空）
- [ ] 1.3.8 提交 commit

### 模块 1.4 — JSON 数据加载

**目标：** 从 `test/data/` 加载 JSON，构造 Creature/Item/Spell 实例。数据内容直接参考 MVP2.md 手动编写 JSON 文件。

**验收：** `load_creature("goblin_brawler")` 返回完整 Creature 实例。

**文件：**
- `test/core/loader.py`
- `test/data/creatures/goblin_brawler.json`（MVP 第一只怪）
- `test/data/creatures/skeleton.json`
- `test/data/creatures/long_ear_dog.json`
- `test/data/creatures/wild_boar.json`
- `test/data/creatures/bird.json`
- `test/data/creatures/squirrel.json`
- `test/data/creatures/cat.json`
- `test/data/creatures/village_elder.json`
- `test/data/creatures/merchant.json`
- `test/data/creatures/villager.json`
- `test/data/items/weapons.json`
- `test/data/items/armors.json`
- `test/data/items/consumables.json`
- `test/data/spells/magic_missile.json`
- `test/data/spells/shield.json`
- `test/data/spells/cure_wounds.json`
- `test/data/terrain.json`（地形/地表定义，含灌木丛的通行/交互/掩体等级）
- `test/data/classes/fighter.json`
- `test/data/classes/mage.json`
- `test/tests/test_loader.py`

**任务步骤：**

- [ ] 1.4.1 手写 `goblin_brawler.json`（从 MVP2.md 复制数值）
- [ ] 1.4.2 手写 `weapons.json`、`armors.json`、`consumables.json`
- [ ] 1.4.3 手写 `magic_missile.json`、`shield.json`、`cure_wounds.json`
- [ ] 1.4.4 手写 `skeleton.json`
- [ ] 1.4.5 写 `test_load_creature` — 加载地精 JSON，验证字段
- [ ] 1.4.6 实现 `load_creature(name)` → 验证测试通过
- [ ] 1.4.7 写 `test_load_item` — 加载武器 JSON
- [ ] 1.4.8 实现 `load_item(name)` → 验证测试通过
- [ ] 1.4.9 提交 commit

---

## 阶段 2：核心系统

### 模块 2.1 — 移动与碰撞

**目标：** 判断一格是否可通行（地形 + 生物占据 + 体型碰撞规则）。

**参考：** 方案4.md 探索部分（对角移动、困难地形、挤身通过、绕过生物）。

**验收：** Grid 上有墙和生物时，`can_move_to` 正确返回 True/False。

**文件：**
- `test/core/movement.py`
- `test/tests/test_movement.py`

**任务步骤：**

- [ ] 2.1.1 写 `test_basic_movement` — 空地可走、墙不可走
- [ ] 2.1.2 实现 `can_enter(col, row, grid, entities)` → 验证测试通过
- [ ] 2.1.3 写 `test_diagonal_blocked_by_corner` — 对角被墙角阻挡
- [ ] 2.1.4 写 `test_entity_blocking` — 生物占据格不可进入（除非体型差）
- [ ] 2.1.5 实现碰撞规则 → 验证测试通过
- [ ] 2.1.6 提交 commit

### 模块 2.2 — A* 寻路

**目标：** 8 方向 A*，考虑移动代价（困难地形、对角线）。

**验收：** 从 A 到 B 返回最短路径；被墙挡住返回空列表。

**文件：**
- 追加到 `test/core/movement.py`
- 追加到 `test/tests/test_movement.py`

**任务步骤：**

- [ ] 2.2.1 写 `test_astar_simple_path` — 无障碍直线路径
- [ ] 2.2.2 实现 `find_path(grid, entities, start, goal)` → 验证测试通过
- [ ] 2.2.3 写 `test_astar_blocked` — 被墙挡住返回空
- [ ] 2.2.4 写 `test_astar_difficult_terrain` — 困难地形绕路
- [ ] 2.2.5 提交 commit

### 模块 2.3 — 视野（FOV）+ 光照

**目标：** 递归阴影投射 + 三级光照（明亮/微光/黑暗）。黑暗视觉生物在黑暗中视为微光。

**参考：** 方案4.md 视野与光照（明亮光照、微光光照、黑暗、黑暗视觉）。

**验收：** 8 格视野，墙后不可见；黑暗环境无光源时 FOV 为空；火把提供周围 5 格明亮；长耳犬/骷髅在黑暗中可感知 5/8 格（微光）。

**文件：**
- `test/core/fov.py`
- `test/tests/test_fov.py`

**任务步骤：**

- [ ] 2.3.1 写 `test_fov_open_area` — 空地 8 格全可见
- [ ] 2.3.2 实现 `compute_fov(grid, origin, radius)` → 验证测试通过
- [ ] 2.3.3 写 `test_fov_wall_blocks` — 墙后格子不可见
- [ ] 2.3.4 写 `test_fov_diagonal_wall` — 对角墙不挡光
- [ ] 2.3.5 写 `test_fov_dark_no_source` — 黑暗环境无光源 → FOV 返回空
- [ ] 2.3.6 写 `test_fov_torch_radius` — 手持火把 → 周围 5 格明亮
- [ ] 2.3.7 写 `test_darkvision` — 有黑暗视觉的生物在黑暗中视为微光（范围内可见但感知检定劣势）
- [ ] 2.3.8 实现光照等级叠加 → 验证测试通过
- [ ] 2.3.9 提交 commit

### 模块 2.4 — 钟摆时间系统

**目标：** 实现速度机制2.md 的钟摆推进逻辑。`tick_pendulum`、`advanceNPCs`、移动/行动两条推进路径。定时事件挂载（灌木重生 1000 钟摆、饮食值消耗每钟摆 -1）。

**参考：** 速度机制2.md 完整状态机。

**验收：** 玩家按方向键累加 `pendulum_acc_ticks`，跨越 SCALE 线触发钟摆推进；NPC 结算一致；`pendulum_count` 到达 1000 时触发灌木重生回调。

**文件：**
- `test/core/pendulum.py`
- `test/tests/test_pendulum.py`

**任务步骤：**

- [ ] 2.4.1 写 `test_pendulum_basic_tick` — 移动 1 格推进 `SCALE / maxS` ticks
- [ ] 2.4.2 实现 `PendulumClock` + `tick_pendulum()` → 验证测试通过
- [ ] 2.4.3 写 `test_action_cost` — 行动消耗 cost 钟摆
- [ ] 2.4.4 写 `test_npc_advance` — NPC 随钟摆推进移动
- [ ] 2.4.5 实现 `advanceNPCs(delta)` → 验证测试通过
- [ ] 2.4.6 写 `test_combat_mode_freeze_curS` — 战斗模式下 curS 冻结
- [ ] 2.4.7 写 `test_timed_event` — 注册定时事件（1000 钟摆后触发回调）
- [ ] 2.4.8 实现 `register_timed_event(pendulum_count, callback)` → 验证测试通过
- [ ] 2.4.9 提交 commit

### 模块 2.5 — GameState

**目标：** 全局游戏状态类：持有 Grid、实体列表、当前玩家角色、时间、战斗状态。

**验收：** GameState 实例可以添加实体、移动玩家、切换回合。

**文件：**
- `test/core/game_state.py`
- `test/tests/test_game_state.py`

**任务步骤：**

- [ ] 2.5.1 写 `test_gamestate_init` — 初始化含空地图 + 玩家
- [ ] 2.5.2 实现 `GameState` 类 → 验证测试通过
- [ ] 2.5.3 写 `test_gamestate_add_entity` — 添加 NPC
- [ ] 2.5.4 写 `test_gamestate_player_move` — 玩家移动更新坐标
- [ ] 2.5.5 实现移动衔接 → 验证测试通过
- [ ] 2.5.6 提交 commit

### 模块 2.6 — 休息系统

**目标：** 短休（300 钟摆）恢复 50% HP/MP、移除 1 层力竭；长休（1500 钟摆）恢复 100% HP/MP、移除所有力竭。室内/床上的舒适环境回复量翻倍。

**参考：** 方案4.md 长休和短休。

**验收：** 短休后 HP/MP 恢复上限一半；长休后回满；舒适状态下恢复量翻倍（短休也回满）；饮食条为空时无法移除力竭。

**文件：**
- `test/core/rest.py`
- `test/tests/test_rest.py`

**任务步骤：**

- [ ] 2.6.1 写 `test_short_rest` — 短休消耗 300 钟摆，恢复 50% HP/MP，移除 1 层力竭
- [ ] 2.6.2 写 `test_long_rest` — 长休消耗 1500 钟摆，恢复 100% HP/MP，移除所有力竭
- [ ] 2.6.3 写 `test_rest_comfort_bonus` — 舒适状态下回复量翻倍
- [ ] 2.6.4 实现 `short_rest(state)` / `long_rest(state)` / `is_comfortable(pos, map)` → 验证测试通过
- [ ] 2.6.5 提交 commit

---

## 阶段 3：战斗系统

### 模块 3.1 — 先攻排序

**目标：** 参战生物投 D20 + 先攻加值，从大到小排序。

**验收：** 玩家敏捷+1，先攻骰出 15 → 结果 16。平局非敌对优先。

**文件：**
- `test/core/combat/initiative.py`
- `test/tests/test_combat.py`

**任务步骤：**

- [ ] 3.1.1 写 `test_initiative_roll` — 先攻 = D20 + 敏捷调整值
- [ ] 3.1.2 实现 `roll_initiative(entities)` → 验证测试通过，返回排序列表
- [ ] 3.1.3 写 `test_initiative_tiebreaker` — 平局非敌对优先
- [ ] 3.1.4 提交 commit

### 模块 3.2 — 命中与伤害

**目标：** 命中检定（D20 + 调整值 vs AC，1 必败 20 必中）、部位命中概率、伤害结算（含伤害减半规则、重击）、伤害类型与抗性/易伤/免疫。

**参考：** 方案4.md 战斗部分（命中检定、部位概率、重击、伤害减半、伤害类型、易伤/抗性/免疫/吸收）。

**验收：** 长剑攻击地精：D20+力量调整值 >= AC 命中，D20=1 必败，D20=20 必中且重击；掷伤害骰 + 调整值 → 判定部位 → 伤害减半判定；骷髅对穿刺抗性（伤害减半）、对钝击易伤（伤害翻倍）、免疫毒素。

**文件：**
- `test/core/combat/attack.py`
- 追加到 `test/tests/test_combat.py`

**任务步骤：**

- [ ] 3.2.1 写 `test_hit_check` — D20 + mod >= AC 命中
- [ ] 3.2.2 实现 `hit_check(attacker, defender, weapon)` → 验证测试通过
- [ ] 3.2.3 写 `test_auto_miss_on_nat1` — D20=1 必定未命中
- [ ] 3.2.4 写 `test_auto_hit_and_crit_on_nat20` — D20=20 必定命中且触发重击
- [ ] 3.2.5 写 `test_hit_location` — 部位命中概率（类人：躯干 60%、双臂 15%、双腿 15%、头部 10%）
- [ ] 3.2.6 实现 `roll_hit_location(body_type)` → 验证测试通过
- [ ] 3.2.7 写 `test_damage_roll` — 武器伤害骰 + 调整值
- [ ] 3.2.8 实现 `roll_damage(weapon, attacker)` → 验证测试通过
- [ ] 3.2.9 写 `test_damage_halved_if_low_hit` — 命中值 <= AC×1.5 伤害减半
- [ ] 3.2.10 写 `test_critical_double_dice` — 重击时伤害骰翻倍
- [ ] 3.2.11 实现重击逻辑 → 验证测试通过
- [ ] 3.2.12 写 `test_damage_type_resistance` — 穿刺抗性 → 伤害减半
- [ ] 3.2.13 写 `test_damage_type_vulnerability` — 钝击易伤 → 伤害翻倍
- [ ] 3.2.14 写 `test_damage_type_immunity` — 毒素免疫 → 伤害为 0
- [ ] 3.2.15 实现 `apply_damage_type_modifiers(damage, dtype, defender)` → 验证测试通过
- [ ] 3.2.16 写 `test_magic_missile_auto_hit` — 魔法飞弹无需命中检定，必定造成伤害
- [ ] 3.2.17 实现攻击类型分流（attack roll vs auto-hit）→ 验证测试通过
- [ ] 3.2.18 提交 commit

### 模块 3.3 — 死亡与濒死

**目标：** HP 降至 0 → 濒死 → 死亡豁免 → 稳定/死亡。含 D20=1 记两次失败、D20=20 恢复 1 HP 等边界规则。

**验收：** 生命从非 0 降至 0 无濒死受伤；已为 0 再受伤累加濒死受伤；死亡豁免 D20>=10 成功、D20=1 记两次失败、D20=20 恢复 1 HP；3 次成功=稳定、3 次失败=死亡；濒死受伤累积 >= 生命上限 = 立即死亡。

**文件：**
- `test/core/combat/death.py`
- 追加到 `test/tests/test_combat.py`

**任务步骤：**

- [ ] 3.3.1 写 `test_drop_to_zero_no_death_injury` — 非 0→0 不累积濒死受伤
- [ ] 3.3.2 写 `test_death_save_success` — D20 >= 10 豁免成功
- [ ] 3.3.3 实现 `DeathSaves` 类 → 验证测试通过
- [ ] 3.3.4 写 `test_death_save_nat1_counts_twice` — D20=1 记两次失败
- [ ] 3.3.5 写 `test_death_save_nat20_recovers` — D20=20 恢复 1 HP 且结束濒死
- [ ] 3.3.6 写 `test_death_by_three_failures` — 累计 3 次失败 = 死亡
- [ ] 3.3.7 写 `test_death_by_injury_overflow` — 濒死受伤 >= 生命上限 = 立即死亡
- [ ] 3.3.8 写 `test_stabilize` — 伤势稳定恢复到 1 HP
- [ ] 3.3.9 提交 commit

### 模块 3.4 — 削韧

**目标：** 未命中时削减目标韧性。公式：D20 掷骰结果除以 5，向下取整，最低 1。韧性最低为 0（不出现负数）。韧性降为 0 时被击破，陷入**失能**状态，持续 1 战斗轮；状态结束后韧性回满。

**参考：** MVP2.md 标注（未命中削韧 = max(roll//5, 1)），方案4.md 韧性规则。

**验收：** D20 掷出 12 未命中 → 削韧 2；韧性归零 → 陷入失能（1 轮）→ 回合结束韧性回满；韧性不会降到负数。

**文件：**
- 追加到 `test/core/combat/attack.py`
- 追加到 `test/tests/test_combat.py`

**任务步骤：**

- [ ] 3.4.1 写 `test_tenacity_reduce_on_miss` — 未命中削韧 = max(d20_roll//5, 1)
- [ ] 3.4.2 实现削韧逻辑（韧性最低为 0）→ 验证测试通过
- [ ] 3.4.3 写 `test_tenacity_break_incapacitated` — 韧性归零 → 陷入失能状态
- [ ] 3.4.4 写 `test_tenacity_break_duration` — 失能持续 1 战斗轮，结束后韧性回满
- [ ] 3.4.5 写 `test_tenacity_cannot_go_negative` — 韧性已为 0 时再削韧保持为 0
- [ ] 3.4.6 提交 commit

### 模块 3.5 — 掩体结算

**目标：** 远程直线攻击沿弹道逐个检查掩体。半身掩体自身 AC 5，四分之三掩体自身 AC 8。攻击骰 >= 掩体 AC → 攻击被掩体阻挡；攻击骰 < 掩体 AC → 穿过继续飞行。全身掩体（如墙壁）直接阻挡。暂定掩体不被破坏、弹药不弹射，命中掩体即终止。投掷武器走抛物线，无视同一高度的掩体。

**参考：** 方案4.md 掩护部分。

**验收：** 攻击穿过半身掩体时先与 AC 5 比较；穿过四分之三掩体时与 AC 8 比较；命中掩体后攻击停止；投掷武器不受同高度掩体影响；全身掩体直接阻挡。

**文件：**
- `test/core/combat/cover.py`
- 追加到 `test/tests/test_combat.py`

**任务步骤：**

- [ ] 3.5.1 写 `test_half_cover_intercepts` — 半身掩体 AC 5，攻击骰 >= 5 命中掩体
- [ ] 3.5.2 写 `test_three_quarter_cover_intercepts` — 四分之三掩体 AC 8
- [ ] 3.5.3 写 `test_attack_passes_cover` — 攻击骰 < 掩体 AC → 穿过
- [ ] 3.5.4 写 `test_full_cover_blocks` — 全身掩体直接阻挡（不可穿过）
- [ ] 3.5.5 写 `test_thrown_weapon_ignores_cover` — 投掷武器走抛物线，无视同高度掩体
- [ ] 3.5.6 实现 `resolve_cover_line(attack_roll, attacker, target, grid, weapon)` → 验证测试通过
- [ ] 3.5.7 提交 commit

---

## 阶段 4：AI 系统

### 模块 4.1 — 状态离散化

**目标：** `discretize_state(npc, ctx)` 将连续状态转为离散键集合。

**参考：** 补充1.md 第 1.3 节。

**验收：** HP=5/20 → `"hp:critical"`；附近 0 盟友 → `"social:alone"`。

**文件：**
- `test/core/ai/discretize.py`
- `test/tests/test_ai.py`

**任务步骤：**

- [ ] 4.1.1 写 `test_discretize_hp_critical` — HP < 20% → "hp:critical"
- [ ] 4.1.2 实现 `discretize_state(npc, ctx)` → 验证测试通过
- [ ] 4.1.3 写 `test_discretize_power_ratio` — 战力对比 → 对应键
- [ ] 4.1.4 写 `test_discretize_on_fire` — 燃烧状态 → "status:on_fire"
- [ ] 4.1.5 验证所有状态键正确生成 → 提交 commit

### 模块 4.2 — AI 行为数据 JSON

**目标：** 编写地精打手和骷髅的 AI 规则 JSON（权重 + 维度表 + 硬过滤）。

**参考：** 补充1.md 第 1.4 节。

**文件：**
- `test/data/ai/goblin_brawler.json`
- `test/data/ai/skeleton.json`

**任务步骤：**

- [ ] 4.2.1 手写 `goblin_brawler.json` AI 规则
- [ ] 4.2.2 手写 `skeleton.json` AI 规则
- [ ] 4.2.3 写 JSON 结构合法性测试 → 提交 commit

### 模块 4.3 — AI 引擎

**目标：** 加载 JSON → 预乘权重 → 查表决策。单层循环，Counter 累加。

**参考：** 补充1.md 第 1.5 节。

**验收：** HP 极低的地精决策为 `"flee"` 得分最高；骷髅死战不退。

**文件：**
- `test/core/ai/loader.py`
- `test/core/ai/engine.py`
- 追加到 `test/tests/test_ai.py`

**任务步骤：**

- [ ] 4.3.1 写 `test_load_behavior` — 加载 JSON，预乘权重正确
- [ ] 4.3.2 实现 `BehaviorLoader` + `BehaviorEngine.__init__`
- [ ] 4.3.3 写 `test_goblin_flees_when_critical` — HP 极低地精→"flee" 最高分
- [ ] 4.3.4 实现 `BehaviorEngine.decide()` → 验证测试通过
- [ ] 4.3.5 写 `test_skeleton_never_flees` — 骷髅永远"attack"最高分
- [ ] 4.3.6 写 `test_hard_filter_blocks_no_weapon` — 无武器时"attack"被过滤
- [ ] 4.3.7 验证硬过滤逻辑 → 提交 commit

---

## 阶段 5：渲染层

### 模块 5.1 — 渲染器抽象接口

**目标：** 定义 `Renderer` 抽象类，`render(state: GameState)` 方法签名。

**文件：**
- `test/render/renderer.py`

**任务步骤：**

- [ ] 5.1.1 定义 `Renderer` ABC，含 `render(state)` 抽象方法
- [ ] 5.1.2 提交 commit

### 模块 5.2 — 动画数据类

**目标：** `AnimationDef`、`AnimationCell` 数据类，纯 ASCII 字符。

**参考：** 补充1.md 第 2.3 节。

**文件：**
- `test/render/animation.py`

**任务步骤：**

- [ ] 5.2.1 定义 `AnimationCell(dx, dy, ch, color)`
- [ ] 5.2.2 定义 `AnimationDef(name, frames, frame_duration, loop)`
- [ ] 5.2.3 提交 commit

### 模块 5.3 — Textual 地图渲染

**目标：** 4 层叠加地图视图（地形层 + 实体层 + 状态层 + 特效层）。

**文件：**
- `test/render/textual/app.py`（Textual App 入口）
- `test/render/textual/widgets/map_view.py`（MapView 容器）
- `test/render/textual/layers/terrain_layer.py`
- `test/render/textual/layers/entity_layer.py`
- `test/render/textual/layers/status_layer.py`
- `test/render/textual/layers/effect_layer.py`

**验收：** 启动 App → 显示地图 → 按方向键移动 `@` → 地图跟随滚动。

**任务步骤：**

- [ ] 5.3.1 实现 `TerrainLayer`：读取 `Grid[Terrain]`，渲染 `.` `#` `~`
- [ ] 5.3.2 实现 `EntityLayer`：渲染 `@` 和 NPC 字符，FOV 外不可见
- [ ] 5.3.3 实现 `StatusLayer`：头顶行显示 `z` `!` 等标记
- [ ] 5.3.4 实现 `EffectLayer`：管理短生命周期动画 Widget
- [ ] 5.3.5 实现 `MapView`：组合 4 层，处理键盘输入
- [ ] 5.3.6 实现 `App`：挂载 MapView，启动游戏循环
- [ ] 5.3.7 手动测试：启动 App，方向键移动 @
- [ ] 5.3.8 提交 commit

### 模块 5.4 — UI 面板

**目标：** 日志面板、角色状态面板、动作栏、输入栏。

**文件：**
- `test/render/textual/widgets/log_panel.py`
- `test/render/textual/widgets/status_panel.py`
- `test/render/textual/widgets/action_bar.py`
- `test/render/textual/widgets/input_bar.py`
- `test/render/textual/screens/main_game.py`（组合所有面板）

**验收：** 主界面显示地图+日志+状态+动作栏+输入栏，布局参考方案4.md。

**任务步骤：**

- [ ] 5.4.1 实现 `LogPanel`：滚动日志，中文 Rich 文本
- [ ] 5.4.2 实现 `StatusPanel`：HP/MP/AC/状态显示
- [ ] 5.4.3 实现 `ActionBar`：动作列表（交互/探查/跳跃等）
- [ ] 5.4.4 实现 `InputBar`：`:命令` 输入 + 回车执行
- [ ] 5.4.5 实现 `MainGameScreen`：组合所有 widget，布局
- [ ] 5.4.6 提交 commit

---

## 阶段 6：游戏流程串联

### 模块 6.1 — 角色创建

**目标：** 标题画面 → 选择战士/魔法使 → 确认属性 → 进入游戏。

**文件：**
- `test/render/textual/screens/title.py`
- `test/render/textual/screens/char_create.py`

**任务步骤：**

- [ ] 6.1.1 实现标题画面：ASCII 艺术标题 + "按 Enter 开始"
- [ ] 6.1.2 实现角色创建：选择职业 → 显示属性 → 确认
- [ ] 6.1.3 创建玩家 Creature 实例，注入 GameState
- [ ] 6.1.4 提交 commit

### 模块 6.2 — 地图加载与切换

**目标：** 加载预设/程序地图。村庄房屋用墙 `#` + 门 `+` 围成可进入区域（非独立地图）。平原/森林随机分布灌木丛。动物在森林区域生物量更高。

**文件：**
- `test/data/maps/village.json`
- `test/data/maps/goblin_camp.json`
- 追加到 `test/core/game_state.py`（地图切换逻辑）
- `test/core/map/generation/bsp.py`（BSP 地城）
- `test/core/map/generation/plains.py`（平原/森林生成 + 灌木丛 + 动物分布）

**任务步骤：**

- [ ] 6.2.1 手写 `village.json`（20×15，含 NPC；房屋用墙 `#` 和门 `+` 围合，墙阻挡视野，内部有床铺标记）
- [ ] 6.2.2 手写 `goblin_camp.json`（10×15，含敌人和篝火；简易木屋为墙+门围合）
- [ ] 6.2.3 实现平原/森林生成：30×30，噪声地形；随机放置灌木丛（森林密度更高）；按生物量分布随机放置动物
- [ ] 6.2.4 实现 BSP 地城生成（3-5 房间+走廊，黑暗环境，入口为楼梯 `>`）
- [ ] 6.2.5 实现 `load_map(name)` → 构造 Grid + 填充实体
- [ ] 6.2.6 实现地图切换：走到边缘 → 加载下一张地图，玩家置于对应边缘
- [ ] 6.2.7 手动测试：村庄地图正常显示，房屋可进入，墙阻挡视野
- [ ] 6.2.8 提交 commit

### 模块 6.3 — NPC 交互与任务

**目标：** 靠近 NPC/物体 → 按 0 交互 → 显示选项。长老给任务，商人交易，灌木丛采摘浆果。

**任务步骤：**

- [ ] 6.3.1 实现通用交互：检查相邻/同格 → 根据目标类型弹出选项菜单
- [ ] 6.3.2 实现长老：对话 → 接受任务（取回红宝石）→ 记录到 GameState
- [ ] 6.3.3 实现商人：对话 → [交易]选项（半价收购，商品列表见 MVP2.md）
- [ ] 6.3.4 实现灌木丛交互：采摘 → 随机获得 1-4 个浆果 → 灌木丛标记为空 → 注册 1000 钟摆重生事件
- [ ] 6.3.5 实现床铺交互：室内床铺 → [休息]选项 → 触发短休/长休（舒适环境）
- [ ] 6.3.6 提交 commit

### 模块 6.4 — 战斗循环

**目标：** 进入战斗 → 先攻排序 → 回合制战斗 → 击杀/逃跑 → 脱战。

**任务步骤：**

- [ ] 6.4.1 实现战斗入口：攻击/被攻击 → 投先攻 → 标记参战
- [ ] 6.4.2 实现玩家回合：选择动作 → 选择目标 → 结算
- [ ] 6.4.3 实现 NPC 回合：调用 AI 引擎决策 → 执行动作
- [ ] 6.4.4 实现战斗结束：所有敌人死亡/脱战 → 移除参战标记
- [ ] 6.4.5 实现逃离战斗：移动 10 格以上 → 脱战
- [ ] 6.4.6 手动测试：村庄触发战斗（攻击 NPC 测试）→ 战斗循环正常
- [ ] 6.4.7 提交 commit

### 模块 6.5 — MVP 完整流程

**目标：** 创建角色 → 村庄接任务 → 穿平原（采摘浆果、遭遇游荡动物）→ 清地精营地 → 进黑暗地城（需火把照明）→ 打骷髅 → 取红宝石 → 回村交任务。

**任务步骤：**

- [ ] 6.5.1 实现动物随机刷新：平原/森林区域按生物量权重随机放置生物（森林密度更高），死亡后不重生（MVP 暂定）
- [ ] 6.5.2 地城中放置骷髅 ×4 和红宝石，环境标记为黑暗
- [ ] 6.5.3 实现搜刮：交互生物尸体或失能生物 → 投 2d6 总和 vs DC → 获得掉落物（同一生物限一次）
- [ ] 6.5.4 实现任务完成判定：红宝石在物品栏 → 回村与长老对话交任务
- [ ] 6.5.5 实现物品栏基本操作：查看、使用（吃/喝/装备）、丢弃
- [ ] 6.5.6 端到端手动测试：完整流程可走通（含采摘浆果、火把照明、舒适休息）
- [ ] 6.5.7 提交 commit

---

## 阶段 7：收尾

### 模块 7.1 — 基本存档

**目标：** 快速存档 F5 / 快速读档 F9，SQLite 单存档槽。

**文件：**
- `test/core/save/database.py`

**任务步骤：**

- [ ] 7.1.1 实现 `save_game(state, slot)` → SQLite
- [ ] 7.1.2 实现 `load_game(slot)` → 恢复 GameState
- [ ] 7.1.3 绑定 F5（存档）F9（读档）快捷键
- [ ] 7.1.4 手动测试：存档 → 移动 → 读档 → 回到原位
- [ ] 7.1.5 提交 commit

### 模块 7.2 — 运行全部测试

**任务步骤：**

- [ ] 7.2.1 `pytest test/tests/ -v` → 确认全部通过
- [ ] 7.2.2 检查 core/ 无 render 依赖
- [ ] 7.2.3 清理调试代码和 print
- [ ] 7.2.4 提交 commit

---

## 优先级速查

| 优先级 | 阶段 | 说明 |
|--------|------|------|
| P0 | 0–2 | 基础设施，不完成无法继续 |
| P1 | 3–4 | 战斗和 AI，核心玩法 |
| P2 | 5 | 渲染，让游戏可见 |
| P3 | 6 | 流程串联，让游戏可玩 |
| P4 | 7 | 收尾，存档和测试 |

**每个模块结束后提交一次 commit，message 格式：`feat(module): description`**
