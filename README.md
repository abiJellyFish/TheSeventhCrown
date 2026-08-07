# ASCII CRPG - MVP 原型

纯 ASCII 字符风格的经典 CRPG 最小可运行原型，基于 Textual TUI 框架。

## 快速启动

```bash
# 安装依赖
cd test
pip install -r requirements.txt

# 启动游戏
python main.py
```

或直接双击项目根目录的 `start.bat` (Windows) / `start.sh` (Linux/macOS)。

## 操作说明

| 按键 | 功能 |
|------|------|
| 方向键 / WASD | 移动角色 |
| Tab | 攻击相邻敌人 / 与相邻 NPC 交谈 |
| R | 短休 (恢复 50% HP/MP) |
| F5 | 快速存档 |
| F9 | 快速读档 |
| Q | 退出游戏 |

## 界面布局

```
+----------------------------------------------------------+
|  [Header]  地名            [COMBAT] 战斗模式标志            |
+-----------------------------------+----------------------+
|                                   |  凯恩                |
|         ASCII 地图                 |  HP: 30/35           |
|                                   |  MP: 0/0             |
|   @ = 玩家  g = 地精              |  TEN: 10/10          |
|   . = 草地  # = 墙壁              |  AC: 8               |
|   " = 灌木丛                      +----------------------+
|                                   |                      |
|                                   |  日志面板              |
|                                   |  > 按方向键移动 @     |
|                                   |  > 命中地精, 5伤害    |
+-----------------------------------+----------------------+
```

## 项目结构

```
test/
├── main.py                      # 游戏入口
├── requirements.txt             # Python 依赖 (textual, pytest)
│
├── core/                        # 游戏逻辑层 (零渲染依赖)
│   ├── dice.py                  # D20 骰子池, 优势劣势叠加抵消
│   ├── grid.py                  # Grid[T] 泛型二维网格
│   ├── entity.py                # Creature, Player, Item, Weapon, Armor
│   ├── loader.py                # JSON 数据加载器
│   ├── movement.py              # 通行判断, A* 寻路
│   ├── fov.py                   # 射线投射视野, 三级光照, 黑暗视觉
│   ├── pendulum.py              # 钟摆时钟, 定时事件
│   ├── game_state.py            # 全局游戏状态
│   ├── rest.py                  # 短休/长休, 舒适加成
│   ├── combat/
│   │   ├── initiative.py        # 先攻排序
│   │   ├── attack.py            # 命中/伤害/重击/伤害类型/自动命中
│   │   ├── death.py             # 死亡豁免/濒死受伤
│   │   └── cover.py             # 掩体射线结算
│   ├── ai/
│   │   ├── discretize.py        # 状态离散化 (唯一有 if-else 的地方)
│   │   └── engine.py            # 查表决策引擎 (Counter 累加)
│   └── save/
│       └── database.py          # JSON 存档管理
│
├── data/                        # 静态 JSON 数据
│   ├── creatures.json           # 10 种生物 (地精/骷髅/野猪/鸟/...)
│   ├── items/                   # 武器/护甲/消耗品
│   ├── spells.json              # 法术定义
│   ├── terrain.json             # 地形/地表
│   ├── classes/                 # 职业路线 (战士/魔法使)
│   ├── ai/                      # AI 行为规则表 (地精/骷髅)
│   └── maps/                    # 地图数据 (村庄/地精营地)
│
├── render/                      # 渲染层
│   ├── renderer.py              # Renderer 抽象接口
│   ├── animation.py             # 动画数据 (纯 ASCII 95 字符集)
│   └── textual/app.py           # Textual 游戏 App
│
├── tests/                       # pytest 测试 (120 个)
│   ├── test_dice.py
│   ├── test_grid.py
│   ├── test_entity.py
│   ├── test_loader.py
│   ├── test_movement.py
│   ├── test_fov.py
│   ├── test_pendulum.py
│   ├── test_game_state.py
│   ├── test_rest.py
│   ├── test_combat.py
│   └── test_ai.py
│
└── docs/                        # 设计文档副本
    ├── 方案4.md                 # 完整游戏设计
    ├── MVP2.md                  # MVP 数据集
    ├── 补充1.md                 # AI & 渲染方案
    └── 速度机制2.md             # 时间系统设计
```

## 技术栈

| 层 | 技术 |
|----|------|
| UI 框架 | Textual (Python TUI) |
| 游戏逻辑 | 纯 Python, 零渲染依赖 |
| 静态数据 | JSON |
| 测试 | pytest (120 个, TDD) |
| 最低 Python | 3.12 |

## 运行测试

```bash
cd test
python -m pytest tests/ -v
```

## MVP 阶段范围

- 人类战士角色
- 村庄 → 平原 → 地精营地 地图探索
- 回合制战斗 (命中/伤害/重击/削韧/死亡豁免)
- NPC AI (地精/骷髅 行为查表)
- 短休/长休 + 舒适加成
- 快速存档/读档

详见 `test/docs/MVP2.md` 和 `test/MVP开发任务.md`。
