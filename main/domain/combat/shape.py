"""多格目标形状 —— 形状解析、光标定位与旋转（瞄准系统基础设施）。

形状由 "WxH" 规格描述（如 "1x3" 表示 1 行 × 3 列）。
坐标体系与网格一致：(col, row)，col 向右、row 向下。
锚格 = 观察光标所在格（形状左上角），旋转圆心 = 形状右上格（col 最大、row 最小）。
"""

from dataclasses import dataclass
from domain.entity.rules import SIZE_RANK, size_rank


@dataclass(frozen=True)
class TargetShape:
    """多格目标形状：相对锚格（光标格）的偏移列表。"""
    offsets: tuple[tuple[int, int, int], ...] = ((0, 0, 0),)
    pivot: tuple | None = None
    base_offsets: tuple[tuple, ...] | None = None
    rotation_steps: int = 0
    rotation_plane: str = "XY"

    @property
    def is_single(self) -> bool:
        return len(self.offsets) <= 1


def entity_reach(entity) -> int:
    """返回实体的固有触及范围；未指定时按体型提供默认值。"""
    explicit = getattr(entity, "reach", None)
    if explicit is not None:
        return max(0, int(explicit))
    return 2 if size_rank(getattr(entity, "size", "medium")) > SIZE_RANK["medium"] else 1


def weapon_melee_reach(weapon, wielder=None) -> int:
    """返回武器近战范围；远程武器也可通过 melee_range 定义近战范围。"""
    if weapon is None:
        return entity_reach(wielder) if wielder is not None else 1
    value = getattr(weapon, "melee_range", None)
    if value is None and getattr(weapon, "melee", None):
        value = weapon.melee.get("melee_range")
    if value is None:
        value = getattr(weapon, "reach", None)
    if value is None:
        value = entity_reach(wielder) if wielder is not None else 1
    return max(0, int(value))


def cells_in_reach(origin: tuple[int, int, int], reach: int) -> set[tuple[int, int, int]]:
    """返回三维立方体触及范围。"""
    return cells_in_range_3d(origin, reach)


def cells_in_range_3d(origin: tuple[int, int, int], reach: int) -> set[tuple[int, int, int]]:
    """返回三维立方体范围，使用 Chebyshev 距离。"""
    ox, oy, oz = origin
    return {
        (ox + dx, oy + dy, oz + dz)
        for dx in range(-reach, reach + 1)
        for dy in range(-reach, reach + 1)
        for dz in range(-reach, reach + 1)
        if max(abs(dx), abs(dy), abs(dz)) <= reach
    }


def is_in_reach(
    origin: tuple[int, int, int], target: tuple[int, int, int], reach: int
) -> bool:
    """判断三维目标格是否在触及范围内。"""
    return max(abs(target[i] - origin[i]) for i in range(3)) <= reach


def parse_shape(spec: str | None) -> TargetShape:
    """解析严格的 WxHxD 形状规格。"""
    if not spec:
        return TargetShape()
    parts = spec.lower().split("x")
    if len(parts) != 3:
        raise ValueError("形状规格必须是 WxHxD")
    try:
        width, height, depth = (int(value) for value in parts)
    except ValueError as exc:
        raise ValueError("形状尺寸必须是整数") from exc
    if min(width, height, depth) < 1:
        raise ValueError("形状尺寸必须大于零")
    offsets = tuple(
        (x, y, z)
        for z in range(depth)
        for y in range(height)
        for x in range(width)
    )
    return TargetShape(offsets, pivot=(0, 0, 0), base_offsets=offsets)


def _shape_spec(pending_attack: dict) -> str:
    return (
        pending_attack.get("target_shape", "")
        or pending_attack.get("spell", {}).get("target_shape", "")
        or ""
    )


def shape_from_pending_attack(pending_attack: dict) -> TargetShape:
    """读取瞄准阶段当前形状，优先使用旋转后的偏移。"""
    rotation_steps = pending_attack.get("target_rotation", 0)
    if rotation_steps:
        base = parse_shape(_shape_spec(pending_attack))
        return _shape_at_rotation_3d(
            base,
            pending_attack.get("target_rotation_plane", "XY"),
            rotation_steps,
        )
    offsets = pending_attack.get("target_offsets")
    if offsets:
        if any(len(offset) != 3 for offset in offsets):
            raise ValueError("目标形状偏移必须是三维坐标")
        return TargetShape(
            tuple(tuple(offset) for offset in offsets),
            pivot=(0, 0, 0),
            rotation_plane=pending_attack.get("target_rotation_plane", "XY"),
        )
    return parse_shape(_shape_spec(pending_attack))


def pivot_offset(shape: TargetShape) -> tuple[int, int, int]:
    """返回三维形状的右上前角旋转圆心。"""
    return (
        max(offset[0] for offset in shape.offsets),
        min(offset[1] for offset in shape.offsets),
        min(offset[2] for offset in shape.offsets),
    )


def rotate_shape_3d(
    shape: TargetShape, plane: str = "XY", clockwise: bool = True
) -> TargetShape:
    """绕指定坐标平面旋转三维形状，返回归一化偏移。"""
    if not shape.offsets or len(shape.offsets[0]) != 3:
        raise ValueError("三维旋转需要三维形状")
    plane = plane.upper()
    if plane not in {"XY", "XZ", "YZ"}:
        raise ValueError("旋转平面必须是 XY、XZ 或 YZ")
    steps = (shape.rotation_steps + (1 if clockwise else -1)) % 8
    return _shape_at_rotation_3d(shape, plane, steps)


def _shape_at_rotation_3d(
    shape: TargetShape, plane: str, steps: int
) -> TargetShape:
    """按指定平面逐格旋转三维形状，方向总数固定为八个。"""
    plane = plane.upper()
    if plane not in {"XY", "XZ", "YZ"}:
        raise ValueError("旋转平面必须是 XY、XZ 或 YZ")
    base = shape.base_offsets or shape.offsets
    axis_a, axis_b = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}[plane]
    pivot_a = max(offset[axis_a] for offset in base)
    pivot_b = min(offset[axis_b] for offset in base)
    rotated = [list(offset) for offset in base]
    for _ in range(steps % 8):
        for value in rotated:
            da = value[axis_a] - pivot_a
            db = value[axis_b] - pivot_b
            na, nb = _rotate_discrete_pair(da, db)
            value[axis_a] = pivot_a + na
            value[axis_b] = pivot_b + nb
    mins = [min(value[index] for value in rotated) for index in range(3)]
    normalized = tuple(sorted(
        tuple(value[index] - mins[index] for index in range(3))
        for value in rotated
    ))
    return TargetShape(
        normalized,
        pivot=(0, 0, 0),
        base_offsets=tuple(base),
        rotation_steps=steps % 8,
        rotation_plane=plane,
    )


def _rotate_discrete_pair(a: int, b: int) -> tuple[int, int]:
    """将一个平面向量推进一个离散 45 度方向。"""
    distance = max(abs(a), abs(b))
    if distance == 0:
        return 0, 0
    directions = (
        (1, 0), (1, 1), (0, 1), (-1, 1),
        (-1, 0), (-1, -1), (0, -1), (1, -1),
    )
    if abs(a) >= abs(b):
        index = 0 if a > 0 else 4
        if b > 0:
            index = 1 if a > 0 else 3
        elif b < 0:
            index = 7 if a > 0 else 5
    else:
        index = 2 if b > 0 else 6
        if a < 0:
            index = 3 if b > 0 else 5
    na, nb = directions[(index + 1) % 8]
    return na * distance, nb * distance


def _shape_at_rotation(shape: TargetShape, steps: int) -> TargetShape:
    """返回离散 45 度方向；偶数方向使用精确 90 度矩形变换。"""
    base = shape.base_offsets or shape.offsets
    steps %= 8
    if steps % 2 == 0:
        offsets = _rotate_quarter_turns(base, steps // 2)
    else:
        offsets = _rotate_diagonal_once(base)
        if steps >= 3:
            offsets = _rotate_quarter_turns(offsets, steps // 2)
    return TargetShape(
        tuple(offsets),
        pivot=(0, 0),
        base_offsets=tuple(base),
        rotation_steps=steps,
    )


def _rotate_quarter_turns(offsets: tuple[tuple[int, int], ...], turns: int) -> tuple[tuple[int, int], ...]:
    result = tuple(offsets)
    for _ in range(turns % 4):
        max_row = max(row for _, row in result)
        result = tuple(
            (max_row - row, col)
            for col, row in result
        )
        min_col = min(col for col, _ in result)
        min_row = min(row for _, row in result)
        result = tuple((col - min_col, row - min_row) for col, row in result)
    return tuple(sorted(result))


def _rotate_diagonal_once(offsets: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """将连续形状离散到一次 45 度方向并保持格子连续。"""
    if len(offsets) > 4:
        row_count = max(2, round(len(offsets) ** 0.5))
        col_count = (len(offsets) + row_count - 1) // row_count
        cells = []
        for row in range(row_count):
            start = row % 2
            for col in range(col_count):
                if len(cells) == len(offsets):
                    break
                cells.append((col + start, row))
        min_col = min(col for col, _ in cells)
        min_row = min(row for _, row in cells)
        return tuple(sorted((col - min_col, row - min_row) for col, row in cells))

    source = TargetShape(tuple(offsets), pivot=pivot_offset(TargetShape(tuple(offsets))))
    px, py = source.pivot or pivot_offset(source)
    rotated = []
    for ox, oy in source.offsets:
        dx, dy = ox - px, oy - py
        distance = max(abs(dx), abs(dy))
        if distance == 0:
            rotated.append((0, 0))
            continue
        direction = (0, 0)
        if dx < 0 and dy == 0:
            direction = (-1, 1)
        elif dx < 0 and dy > 0:
            direction = (0, 1)
        elif dx == 0 and dy > 0:
            direction = (1, 1)
        elif dx > 0 and dy > 0:
            direction = (1, 0)
        elif dx > 0 and dy == 0:
            direction = (1, -1)
        elif dx > 0 and dy < 0:
            direction = (0, -1)
        elif dx == 0 and dy < 0:
            direction = (-1, -1)
        else:
            direction = (0, -1)
        rotated.append((direction[0] * distance, direction[1] * distance))
    unique = set(rotated)
    if len(unique) == len(rotated):
        return tuple(sorted(unique))
    return tuple(sorted(_fill_connected_cells(unique, len(rotated))))


def _fill_connected_cells(
    cells: set[tuple[int, int]],
    target_count: int,
) -> set[tuple[int, int]]:
    """用相邻格补齐离散旋转中的碰撞，不改变形状格子总数。"""
    result = set(cells)
    frontier = set(cells)
    while len(result) < target_count:
        candidates = {
            (col + dc, row + dr)
            for col, row in frontier
            for dc, dr in (
                (-1, -1), (-1, 0), (-1, 1), (0, -1),
                (0, 1), (1, -1), (1, 0), (1, 1),
            )
            if (col + dc, row + dr) not in result
        }
        if not candidates:
            break
        chosen = min(candidates, key=lambda pos: (pos[1], pos[0]))
        result.add(chosen)
        frontier.add(chosen)
    return result


def shape_cells(
    anchor: tuple[int, int, int], shape: TargetShape
) -> list[tuple[int, int, int]]:
    """三维锚点加偏移得到绝对坐标。"""
    if len(anchor) != 3:
        raise ValueError("形状锚点必须是三维坐标")
    return [
        (anchor[0] + offset[0], anchor[1] + offset[1], anchor[2] + offset[2])
        for offset in shape.offsets
    ]


def is_contiguous_shape(shape: TargetShape) -> bool:
    """判断范围格是否通过三维相邻格连成一个整体。"""
    cells = set(shape.offsets)
    if len(cells) <= 1:
        return True
    reached = {next(iter(cells))}
    pending = list(reached)
    while pending:
        current = pending.pop()
        for candidate in cells - reached:
            if max(
                abs(candidate[index] - current[index]) for index in range(3)
            ) <= 1:
                reached.add(candidate)
                pending.append(candidate)
    return len(reached) == len(cells)
