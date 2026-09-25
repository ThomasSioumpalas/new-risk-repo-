"""Identity, API keys and role-based permissions.

* API keys are 256-bit random tokens. Only their SHA-256 digest is stored, so a
  database leak does not leak usable keys. Lookup is by digest: a timing
  side channel reveals nothing usable about a random 256-bit key.
* Permissions follow least privilege. The administrator manages users but has
  **no** risk-decision rights. Technical privilege is not business
  accountability.
* Segregation of duties that depends on the *object* (for example "you cannot
  accept an assessment you performed") is enforced in the governance service,
  not here.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from enum import StrEnum

from sextant.domain.methodology import Role


class Permission(StrEnum):
    READ = "read"
    READ_AUDIT = "read_audit"
    EDIT_REGISTER = "edit_register"
    RECORD_TESTS = "record_tests"
    ASSESS = "assess"
    OVERRIDE = "override"
    APPROVE_TREATMENT = "approve_treatment"
    ACCEPT_RISK = "accept_risk"
    MANAGE_METHODOLOGY = "manage_methodology"
    MANAGE_USERS = "manage_users"


P = Permission
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({P.READ}),
    Role.AUDITOR: frozenset({P.READ, P.READ_AUDIT}),
    Role.ANALYST: frozenset({P.READ, P.EDIT_REGISTER, P.RECORD_TESTS, P.ASSESS}),
    Role.CONTROL_OWNER: frozenset({P.READ, P.RECORD_TESTS}),
    Role.RISK_OWNER: frozenset({P.READ, P.APPROVE_TREATMENT, P.ACCEPT_RISK}),
    Role.RISK_MANAGER: frozenset(
        {
            P.READ,
            P.READ_AUDIT,
            P.EDIT_REGISTER,
            P.RECORD_TESTS,
            P.ASSESS,
            P.OVERRIDE,
            P.APPROVE_TREATMENT,
            P.ACCEPT_RISK,
            P.MANAGE_METHODOLOGY,
        }
    ),
    Role.EXECUTIVE: frozenset({P.READ, P.APPROVE_TREATMENT, P.ACCEPT_RISK}),
    Role.ADMIN: frozenset({P.READ, P.READ_AUDIT, P.MANAGE_USERS}),
}


@dataclass(frozen=True)
class Actor:
    username: str
    role: Role

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]


def generate_api_key() -> str:
    """A new API key (shown once to the user, never stored)."""
    return "sxt_" + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
