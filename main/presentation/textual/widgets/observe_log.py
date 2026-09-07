"""观察模式：选中实体的个人日志面板。"""


def render_observe_entity_log(state) -> str:
    entity_id = state.observe_log_id
    entity = next(
        (creature for creature, _position in state.entities if id(creature) == entity_id),
        None,
    )
    name = entity.name if entity is not None else "未知"
    lines = [f"[bold]个人日志 — {name}[/] [dim]'返回 X退出[/]", ""]
    messages = state.entity_logs.get(entity_id, [])
    if not messages:
        lines.append("  (无记录)")
    else:
        lines.extend(messages)
    return "\n".join(lines)
