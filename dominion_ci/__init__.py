"""Dominion Dynamics / Flow CI demo: small, verifiable engineering calculations.

Each function implements a software requirement that lives in Flow
(project "Dominion Scout Arctic Anti-Icing Demo"). Tests are tagged with the
Flow test case / requirement IDs so CI results flow straight back into Flow.
"""
from .heater_power import heater_power_command
from .latency_budget import LatencyBudget, LinkConfig, compute_budget

__all__ = ["LatencyBudget", "LinkConfig", "compute_budget", "heater_power_command"]
