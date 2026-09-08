"""Traceable NB/T 47014 special-joint source clauses, without claiming automated qualification."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SOURCE = Path(__file__).resolve().parents[1] / 'business_packs/engineering_inspection_v1/nbt47014_special_qualification_annexes.yaml'


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return yaml.safe_load(SOURCE.read_text())


def special_qualification_source(kind: str, *, clause: str | None = None) -> dict[str, Any] | None:
    asset = _load()
    annex = next((item for item in asset['annexes'] if kind in {item['annex'], item['qualificationKind']}), None)
    if annex is None or (clause is not None and clause not in annex['clauses']):
        return None
    pages = [item for item in annex['pages'] if clause is None or clause in item['text']]
    return deepcopy({'standard': asset['standard'], 'sourcePdf': asset['sourcePdf'], 'sourceSha256': asset['sourceSha256'],
                     'verifiedBy': asset['verifiedBy'], **{key: value for key, value in annex.items() if key != 'pages'},
                     'pages': pages})
