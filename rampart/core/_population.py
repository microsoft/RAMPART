# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared validation for trial population configuration and provenance."""

from __future__ import annotations

import math


def validate_population_id(value: object) -> str:
    """Validate and return a population identifier.

    Returns:
        str: Validated population identifier.

    Raises:
        TypeError: If ``value`` is not a string.
        ValueError: If ``value`` is empty or exceeds the transport bound.
    """
    if not isinstance(value, str):
        msg = "population id must be a string"
        raise TypeError(msg)
    if not value:
        msg = "population id must be non-empty"
        raise ValueError(msg)
    return value


def validate_population_size(
    value: object,
    *,
    name: str,
    allow_zero: bool = False,
) -> int:
    """Validate and return a population size.

    Returns:
        int: Validated population size.

    Raises:
        TypeError: If ``value`` is not a non-boolean integer.
        ValueError: If ``value`` is outside the supported range.
    """
    if type(value) is not int:
        msg = f"{name} must be a non-boolean integer"
        raise TypeError(msg)
    minimum = 0 if allow_zero else 1
    if value < minimum:
        if minimum == 0:
            msg = f"{name} must be greater than or equal to 0"
        else:
            msg = f"{name} must be greater than or equal to 1"
        raise ValueError(msg)
    return value


def validate_population_threshold(value: object, *, name: str) -> float:
    """Validate and return a finite population threshold.

    Returns:
        float: Normalized population threshold.

    Raises:
        TypeError: If ``value`` is not a non-boolean number.
        ValueError: If ``value`` is non-finite or outside [0.0, 1.0].
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{name} must be a number"
        raise TypeError(msg)
    try:
        normalized = float(value)
    except OverflowError as exc:
        msg = f"{name} must be finite"
        raise ValueError(msg) from exc
    if not math.isfinite(normalized):
        msg = f"{name} must be finite"
        raise ValueError(msg)
    if not 0.0 <= normalized <= 1.0:
        msg = f"{name} must be between 0.0 and 1.0"
        raise ValueError(msg)
    return normalized


def validate_population_index(value: object, *, size: int) -> int:
    """Validate and return a population member index.

    Returns:
        int: Validated population index.

    Raises:
        TypeError: If ``value`` is not a non-boolean integer.
        ValueError: If ``value`` falls outside the population.
    """
    if type(value) is not int:
        msg = "population index must be an integer"
        raise TypeError(msg)
    if not 0 <= value < size:
        msg = "population index must be between 0 and size - 1"
        raise ValueError(msg)
    return value


def validate_population_parameters(
    *,
    size: object,
    threshold: object,
    size_name: str,
    threshold_name: str,
    allow_empty: bool = False,
) -> tuple[int, float]:
    """Validate and normalize shared population parameters.

    Returns:
        tuple[int, float]: Validated size and normalized threshold.
    """
    return (
        validate_population_size(
            size,
            name=size_name,
            allow_zero=allow_empty,
        ),
        validate_population_threshold(threshold, name=threshold_name),
    )
