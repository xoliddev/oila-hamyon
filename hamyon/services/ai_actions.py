"""Tugmalardan (AI'siz) amal yaratish - ular ham AI amallari bilan bir xil tekshiruvdan o'tadi."""
from __future__ import annotations

from hamyon.ai.schemas import Action


def make_action(**fields) -> Action:
    base = {name: None for name in Action.model_fields}
    base.update(confidence=1.0)
    base.update(fields)
    return Action(**base)
