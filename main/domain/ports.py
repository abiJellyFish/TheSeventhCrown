"""领域层依赖端口。

领域规则只依赖这些协议，具体文件实现由基础设施层组装。
"""
from typing import Any, Protocol


class RepositoryPort(Protocol):
    def load_entity_data(self, name: str) -> dict | None: ...
    def load_item_data(self, name: str) -> dict | None: ...
    def load_spell_data(self, name: str | None = None) -> Any: ...
    def load_class_data(self, class_name: str) -> dict | None: ...
    def load_shop_data(self, shop_id: str) -> dict | None: ...
    def save_shop_data(self, shop_id: str, data: dict) -> None: ...
    def load_map_data(self, map_name: str) -> dict | None: ...
    def load_actions_data(self) -> list[dict]: ...
    def load_json(self, relative_path: str) -> Any: ...
    def load_all(self, category: str) -> dict[str, dict]: ...


_repository: RepositoryPort | None = None
_action_executor_factory = None


def configure_repository(repository: RepositoryPort) -> None:
    global _repository
    _repository = repository


def get_repository() -> RepositoryPort:
    if _repository is None:
        raise RuntimeError("domain repository has not been configured")
    return _repository


def configure_action_executor(factory) -> None:
    global _action_executor_factory
    _action_executor_factory = factory


def get_action_executor():
    if _action_executor_factory is None:
        raise RuntimeError("domain action executor has not been configured")
    return _action_executor_factory()
