"""应用启动时的基础设施组装。"""
from infrastructure.config import DATA_DIR
from infrastructure.data.repository import DataRepository
from domain.ports import configure_repository


def configure() -> None:
    configure_repository(DataRepository(DATA_DIR))
