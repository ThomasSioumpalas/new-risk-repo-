from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from sextant.api.app import create_app
from sextant.config import Settings
from sextant.db.session import make_engine, make_session_factory, transaction
from sextant.domain.methodology import Role
from sextant.domain.register import load_register
from sextant.services.register import create_user, import_register

ROOT = Path(__file__).resolve().parents[2]


def migrate(url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


class Api:
    """Test client plus one API key per role."""

    def __init__(self, client: TestClient, keys: dict[str, str], url: str) -> None:
        self.client = client
        self.keys = keys
        self.url = url

    def h(self, user: str) -> dict[str, str]:
        return {"X-API-Key": self.keys[user]}

    def get(self, user: str, path: str, **kw: object):  # type: ignore[no-untyped-def]
        return self.client.get(path, headers=self.h(user), **kw)  # type: ignore[arg-type]

    def post(self, user: str, path: str, json: object | None = None, **kw: object):  # type: ignore[no-untyped-def]
        return self.client.post(path, headers=self.h(user), json=json, **kw)  # type: ignore[arg-type]

    def put(self, user: str, path: str, json: object):  # type: ignore[no-untyped-def]
        return self.client.put(path, headers=self.h(user), json=json)


USERS = {
    "vera": Role.VIEWER,
    "audrey": Role.AUDITOR,
    "ana": Role.ANALYST,
    "andy": Role.ANALYST,
    "colin": Role.CONTROL_OWNER,
    "olga": Role.RISK_OWNER,
    "mira": Role.RISK_MANAGER,
    "eve": Role.EXECUTIVE,
    "adam": Role.ADMIN,
}


def _database_url(tmp_path: Path) -> str:
    """SQLite by default; set SEXTANT_TEST_DATABASE_URL to run the same tests on PostgreSQL."""
    url = os.environ.get("SEXTANT_TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path / 'sextant.db'}"
    engine = make_engine(url)
    with engine.begin() as conn:  # fresh schema per test
        conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
    engine.dispose()
    return url


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    url = _database_url(tmp_path)
    migrate(url)
    factory = make_session_factory(make_engine(url))
    register, methodology = load_register(ROOT / "examples" / "halcyon")
    keys: dict[str, str] = {}
    with transaction(factory) as session:
        import_register(session, "seed", register, methodology)
        for name, role in USERS.items():
            keys[name] = create_user(session, None, name, name.title(), role)
    app = create_app(
        Settings(database_url=url, env="test", log_json=True, log_level="WARNING", api_max_trials=20_000)
    )
    with TestClient(app) as client:
        yield Api(client, keys, url)
