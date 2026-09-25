"""Append-only, hash-chained audit trail.

Every state-changing operation writes one entry *in the same database
transaction* as the change. Either both are committed or neither is. Each entry
contains the SHA-256 of its own canonical content plus the previous entry's
hash::

    hashₙ = SHA-256(canonical(seqₙ, tsₙ, actor, action, entity, payload, hashₙ₋₁))

Changing, deleting or reordering any entry breaks every later link, and
:func:`verify_chain` reports the first broken sequence number. Database
triggers (see the migration) additionally reject UPDATE and DELETE.

This is **tamper-evident**, not tamper-proof. Someone with full database
control could rewrite the whole chain. Periodically anchoring the latest hash
outside the database (a WORM store, a ticket, a timestamping authority) closes
that gap and is listed on the roadmap.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from sextant.db.models import AuditEntry, AuditHead
from sextant.services.security import Actor

GENESIS = "0" * 64


def _ts_text(ts: datetime) -> str:
    """Timezone-normalised text form, identical for SQLite (naive) and PostgreSQL (aware) round-trips."""
    if ts.tzinfo is not None:
        ts = ts.astimezone(UTC).replace(tzinfo=None)
    return ts.isoformat(timespec="microseconds")


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def entry_hash(
    seq: int,
    ts: datetime,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    prev_hash: str,
) -> str:
    body = _canonical(
        {
            "seq": seq,
            "ts": _ts_text(ts),
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(body.encode()).hexdigest()


def record(
    session: Session,
    actor: Actor | str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
) -> AuditEntry:
    """Append an audit entry within the caller's transaction."""
    who = actor.username if isinstance(actor, Actor) else actor
    # Normalise to JSON-native types so the hash is stable after the database round-trip.
    data: dict[str, Any] = json.loads(_canonical(payload or {}))
    head = session.get(AuditHead, 1, with_for_update=True)
    if head is None:
        head = AuditHead(id=1, last_seq=0, last_hash=GENESIS)
        session.add(head)
        session.flush()
    seq = head.last_seq + 1
    ts = datetime.now(UTC)
    digest = entry_hash(seq, ts, who, action, entity_type, entity_id, data, head.last_hash)
    entry = AuditEntry(
        seq=seq,
        ts=ts,
        actor=who,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=data,
        prev_hash=head.last_hash,
        hash=digest,
    )
    session.add(entry)
    head.last_seq = seq
    head.last_hash = digest
    session.flush()
    return entry


class ChainVerification(BaseModel):
    ok: bool
    entries: int
    head_hash: str
    first_invalid_seq: int | None = None
    reason: str | None = None


def verify_chain(session: Session) -> ChainVerification:
    prev = GENESIS
    expected_seq = 1
    count = 0
    for e in session.scalars(select(AuditEntry).order_by(AuditEntry.seq)):
        count += 1
        if e.seq != expected_seq:
            return ChainVerification(
                ok=False, entries=count, head_hash=prev, first_invalid_seq=e.seq, reason="gap in sequence"
            )
        if e.prev_hash != prev:
            return ChainVerification(
                ok=False, entries=count, head_hash=prev, first_invalid_seq=e.seq, reason="broken link"
            )
        recomputed = entry_hash(
            e.seq, e.ts, e.actor, e.action, e.entity_type, e.entity_id, e.payload, e.prev_hash
        )
        if recomputed != e.hash:
            return ChainVerification(
                ok=False, entries=count, head_hash=prev, first_invalid_seq=e.seq, reason="content altered"
            )
        prev = e.hash
        expected_seq += 1
    head = session.get(AuditHead, 1)
    if head is not None and (head.last_hash != prev or head.last_seq != count):
        return ChainVerification(
            ok=False,
            entries=count,
            head_hash=prev,
            first_invalid_seq=count,
            reason="entries removed from the end",
        )
    return ChainVerification(ok=True, entries=count, head_hash=prev)


def list_entries(
    session: Session,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 100,
    after_seq: int = 0,
) -> list[AuditEntry]:
    stmt = select(AuditEntry).where(AuditEntry.seq > after_seq).order_by(AuditEntry.seq).limit(limit)
    if entity_type:
        stmt = stmt.where(AuditEntry.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEntry.entity_id == entity_id)
    return list(session.scalars(stmt))
