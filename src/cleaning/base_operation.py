# File: src/cleaning/base_operation.py
"""The shared interface every data cleaning operation implements.

:class:`BaseOperation` enforces one architectural rule that matters
more than any individual operation's logic: **cleaning operations
never mutate a dataset in place.** Every operation takes a source
:class:`~src.services.workspace_service.Dataset` and returns a new
one, with :attr:`~src.services.workspace_service.Dataset.
parent_dataset_id` set to the source's ID and
:attr:`~src.services.workspace_service.Dataset.derivation_description`
describing what changed — using milestone 3a's lineage fields for
their first real purpose. This is not a style preference: mutating in
place would silently invalidate any visualization or further-derived
dataset already built on top of the original, and would make undo
impossible without a separate undo stack. Returning a new, immutable
result sidesteps both problems by construction rather than by
discipline.

Like :class:`~src.readers.base_reader.BaseReader`, every concrete
operation is a stateless classmethod-only class — there is no reason
to instantiate a cleaning operation any more than there was a reader.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.workspace_service import Dataset


class BaseOperation(ABC):
    """Abstract base class every cleaning operation inherits from."""

    @classmethod
    @abstractmethod
    def apply(cls, dataset: "Dataset", **kwargs) -> "Dataset":
        """Apply this operation to ``dataset`` and return a new, derived Dataset.

        Args:
            dataset: The source dataset. Never mutated — its
                ``dataframe`` is not modified in place; if this
                operation needs to change values, it operates on a
                copy.
            **kwargs: Operation-specific parameters (for example,
                which columns to target). Each concrete operation
                documents its own accepted parameters rather than this
                base class declaring a fixed signature, since
                different operations genuinely need different
                parameters and a fixed signature would either be too
                restrictive or too generic to be useful.

        Returns:
            A new :class:`~src.services.workspace_service.Dataset`
            with ``parent_dataset_id`` set to ``dataset.dataset_id``
            and ``derivation_description`` set to a human-readable
            summary of what this operation did.

        Raises:
            ServiceError: If the requested operation cannot be applied
                to this dataset (for example, a named column does not
                exist). Concrete operations document their own
                specific error conditions.
        """
        raise NotImplementedError
