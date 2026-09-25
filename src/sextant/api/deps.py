"""FastAPI dependencies: database session per request and API-key authentication."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from sextant.config import Settings
from sextant.services import register
from sextant.services.security import Actor


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request: committed on success, rolled back on error."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_actor(
    request: Request,
    session: SessionDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Actor:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated", "message": "missing X-API-Key header"},
        )
    actor = register.authenticate(session, x_api_key)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated", "message": "invalid or inactive API key"},
        )
    # Sync endpoints run in a worker thread, so contextvars would not reach the access log;
    # request.state does.
    request.state.actor = actor.username
    structlog.contextvars.bind_contextvars(actor=actor.username)
    return actor


ActorDep = Annotated[Actor, Depends(get_actor)]
