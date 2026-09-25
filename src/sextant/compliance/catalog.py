"""Framework catalogs: requirement sets that controls are mapped to.

Catalogs are data (YAML), shipped with the package. Each one declares its
``license`` and ``text_policy``, so that copyright handling is explicit and
reviewable:

* ``verbatim``: public-domain text (NIST);
* ``abridged``: legislation, shortened (EU law is reusable, and the Official
  Journal is authoritative);
* ``identifiers_with_paraphrased_labels``: copyrighted standards (ISO). Only
  identifiers and short topic labels written for this project are included.
"""

from __future__ import annotations

from enum import StrEnum
from functools import cache
from importlib import resources

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class TextPolicy(StrEnum):
    VERBATIM = "verbatim"
    ABRIDGED = "abridged"
    PARAPHRASED = "identifiers_with_paraphrased_labels"


class CatalogKind(StrEnum):
    CERTIFIABLE = "certifiable_management_system"
    OUTCOME = "outcome_framework"
    REGULATION = "regulation"
    VOLUNTARY = "voluntary_framework"


class Group(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    parent: str = ""


class Requirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    group: str


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    version: str
    publisher: str
    source: str
    license: str
    text_policy: TextPolicy
    kind: CatalogKind
    groups: list[Group]
    requirements: list[Requirement]

    @model_validator(mode="after")
    def _check(self) -> Catalog:
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: duplicate requirement ids")
        group_ids = {g.id for g in self.groups}
        if missing := {r.group for r in self.requirements} - group_ids:
            raise ValueError(f"{self.id}: requirements reference unknown groups {sorted(missing)}")
        return self

    def requirement(self, rid: str) -> Requirement:
        for r in self.requirements:
            if r.id == rid:
                return r
        raise KeyError(f"{self.id}: unknown requirement '{rid}'")

    def has(self, rid: str) -> bool:
        return any(r.id == rid for r in self.requirements)

    def group_title(self, gid: str) -> str:
        return next((g.title for g in self.groups if g.id == gid), gid)


CATALOG_FILES = {
    "iso27001_2022": "iso27001_2022.yaml",
    "nist_csf_2_0": "nist_csf_2_0.yaml",
    "nis2_2022_2555": "nis2_2022_2555.yaml",
    "nist_ai_rmf_1_0": "nist_ai_rmf_1_0.yaml",
}


@cache
def load_catalog(catalog_id: str) -> Catalog:
    if catalog_id not in CATALOG_FILES:
        raise KeyError(f"unknown catalog '{catalog_id}'; available: {sorted(CATALOG_FILES)}")
    text = (
        resources.files("sextant.compliance.catalogs").joinpath(CATALOG_FILES[catalog_id]).read_text("utf-8")
    )
    return Catalog.model_validate(yaml.safe_load(text))


def all_catalogs() -> dict[str, Catalog]:
    return {cid: load_catalog(cid) for cid in CATALOG_FILES}
