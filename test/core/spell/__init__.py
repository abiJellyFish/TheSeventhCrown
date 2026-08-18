"""法术包 —— 法术加载、法术位管理、记忆/替换、施法结算。"""
from core.spell.spell import (
    load_spells,
    load_class_data,
    get_known_spells,
    get_memorized_spells,
    get_spell_slots,
    get_available_slots,
    memorize_spell,
    unmemorize_spell,
    replace_spell,
    spell_save_dc,
    spell_saving_throw,
    resolve_spell,
)

__all__ = [
    "load_spells",
    "load_class_data",
    "get_known_spells",
    "get_memorized_spells",
    "get_spell_slots",
    "get_available_slots",
    "memorize_spell",
    "unmemorize_spell",
    "replace_spell",
    "spell_save_dc",
    "spell_saving_throw",
    "resolve_spell",
]
