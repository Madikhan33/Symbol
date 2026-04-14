"""Decorator API for explicit symbol metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from symbol_memory.core.models import SymbolDecoratorMetadata

DecoratedObjectT = TypeVar("DecoratedObjectT")


def symbol(
    id: str,
    *,
    r: list[str],
    role: str,
    summary: str,
    notes: str | None = None,
    tags: list[str] | None = None,
    expose: bool = True,
    entrypoint: bool = False,
) -> Callable[[DecoratedObjectT], DecoratedObjectT]:
    """Attach validated symbol metadata without wrapping the decorated object."""

    metadata = SymbolDecoratorMetadata(
        id=id,
        r=r,
        role=role,
        summary=summary,
        notes=notes,
        tags=tags or [],
        expose=expose,
        entrypoint=entrypoint,
    )

    def decorate(obj: DecoratedObjectT) -> DecoratedObjectT:
        setattr(obj, "__symbol_metadata__", metadata.model_dump(mode="python"))
        return obj

    return decorate
