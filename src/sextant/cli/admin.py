"""Operator commands: database migration, seeding and user management.

These commands act directly on the database configured by
``SEXTANT_DATABASE_URL``. Anyone who can run them already has database
access, so they are operator privileges, and every change they make is still
written to the audit log (actor ``operator:<os user>``).
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from sextant.config import get_settings
from sextant.db.models import RiskRecord
from sextant.db.session import make_engine, make_session_factory, transaction
from sextant.domain.methodology import Role
from sextant.domain.register import load_register
from sextant.services.register import create_user, import_register

db_app = typer.Typer(help="Database administration.", no_args_is_help=True)
users_app = typer.Typer(help="User and API-key management.", no_args_is_help=True)


def _operator() -> str:
    return f"operator:{getpass.getuser()}"


def _factory() -> sessionmaker[Session]:
    return make_session_factory(make_engine(get_settings().database_url))


@db_app.command("upgrade")
def upgrade(
    alembic_ini: Annotated[Path, typer.Option(help="Path to alembic.ini.")] = Path("alembic.ini"),
) -> None:
    """Apply database migrations (creates tables and audit-protection triggers)."""
    if not alembic_ini.exists():
        typer.echo(f"alembic.ini not found at {alembic_ini}", err=True)
        raise typer.Exit(1)
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
    typer.echo("Database is at the latest schema revision.")


@db_app.command("seed")
def seed(register_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)]) -> None:
    """Import a risk-as-code register into an EMPTY database (demo / migration)."""
    register, methodology = load_register(register_dir)
    with transaction(_factory()) as session:
        if session.scalar(select(func.count()).select_from(RiskRecord)):
            typer.echo("Database already contains risks; refusing to seed.", err=True)
            raise typer.Exit(1)
        counts = import_register(session, _operator(), register, methodology)
    typer.echo(
        f"Imported {counts['risks']} risks, {counts['controls']} controls, {counts['assets']} assets, "
        f"{counts['evidence']} evidence items."
    )


@users_app.command("create")
def create(
    username: Annotated[str, typer.Argument()],
    role: Annotated[Role, typer.Option("--role", help="Role determines permissions.")],
    display_name: Annotated[str, typer.Option("--name")] = "",
) -> None:
    """Create a user and print their API key. The key is shown ONCE and only its hash is stored."""
    with transaction(_factory()) as session:
        key = create_user(session, None, username, display_name or username, role)
    typer.echo(
        f"User '{username}' ({role.value}) created.\nAPI key (store it securely, it is not shown again):"
    )
    typer.echo(key)


@users_app.command("demo")
def demo() -> None:
    """Create one demo user per role (refused when SEXTANT_ENV=production)."""
    if get_settings().env == "production":
        typer.echo("Refusing to create demo users in production.", err=True)
        raise typer.Exit(1)
    with transaction(_factory()) as session:
        keys = {
            role.value: create_user(session, None, f"demo-{role.value}", role.value, role) for role in Role
        }
    typer.echo("Demo users (development only):")
    for role, key in keys.items():
        typer.echo(f"  demo-{role:<14} {key}")
