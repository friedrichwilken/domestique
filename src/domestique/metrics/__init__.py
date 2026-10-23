"""Derived metrics: pure functions over plain data, no I/O, no model.

A *sample* is a dict with keys ``t_s`` (elapsed seconds), ``watts``, ``hr``,
``cadence`` and ``lr`` (left-leg share of power, percent). Values may be None.
An *interval* is a dict with ``start_s`` and ``dur_s`` (plus optional extras).
"""

from domestique.metrics.balance import interval_lr_balance, lr_balance
from domestique.metrics.efficiency import (
    decoupling_pct,
    efficiency_factor,
    normalized_power,
    watts_at_hr_band,
)
from domestique.metrics.timing import hours_before_bed

__all__ = [
    "decoupling_pct",
    "efficiency_factor",
    "hours_before_bed",
    "interval_lr_balance",
    "lr_balance",
    "normalized_power",
    "watts_at_hr_band",
]
