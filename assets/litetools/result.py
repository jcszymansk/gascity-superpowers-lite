"""A minimal Result type, so expected failures are values instead of exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, Union

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    """A successful result carrying ``value``."""

    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    """A failed result carrying ``error``."""

    error: E


Result = Union[Ok[T], Err[E]]
