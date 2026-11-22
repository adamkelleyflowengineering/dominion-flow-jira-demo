"""C2 datalink end-to-end latency budget (implements REQ-45162, allocates REQ-45141).

Budget = GCS serialization + ground terminal + RF segment + air vehicle radio.
The RF segment covers propagation, interleaver/framing delay and, for relay
operation, a second hop plus store-and-forward delay at the relay Scout.

Allocations (from Flow):
  REQ-45141 C2 link end-to-end latency          <= 250 ms
  REQ-45148 RF link propagation and framing     <= 120 ms
  REQ-45147 Ground terminal processing          <=  40 ms (design 32 ms)
  REQ-45149 Air vehicle datalink processing     <=  60 ms (design 54 ms)
  REQ-45150 GCS command serialization           <=  30 ms (design 28 ms)
"""
from __future__ import annotations

from dataclasses import dataclass

SPEED_OF_LIGHT_KM_PER_MS = 299.792458

E2E_LIMIT_MS = 250.0
RF_LIMIT_MS = 120.0

GCS_SERIALIZATION_MS = 28.0
GROUND_TERMINAL_MS = 32.0
AIR_VEHICLE_RADIO_MS = 54.0

MODEM_FIXED_MS = 3.5
FRAME_BASE_MS = 30.0
FRAME_PER_INTERLEAVER_ROW_MS = 4.0
RELAY_STORE_FORWARD_MS = 15.0

VALID_INTERLEAVER_DEPTHS = (4, 8, 16, 32)
MAX_LOS_RANGE_KM = 250.0


@dataclass(frozen=True)
class LinkConfig:
    """One planned C2 link configuration."""

    name: str
    range_km: float
    interleaver_depth: int = 16
    relay: bool = False

    def __post_init__(self) -> None:
        if self.range_km <= 0:
            raise ValueError("range_km must be positive")
        if self.interleaver_depth not in VALID_INTERLEAVER_DEPTHS:
            raise ValueError(f"interleaver_depth must be one of {VALID_INTERLEAVER_DEPTHS}")
        if not self.relay and self.range_km > MAX_LOS_RANGE_KM:
            raise ValueError("line-of-sight range above 250 km requires relay")


@dataclass(frozen=True)
class LatencyBudget:
    config: LinkConfig
    gcs_ms: float
    ground_terminal_ms: float
    rf_ms: float
    air_vehicle_ms: float

    @property
    def total_ms(self) -> float:
        return self.gcs_ms + self.ground_terminal_ms + self.rf_ms + self.air_vehicle_ms

    @property
    def rf_within_limit(self) -> bool:
        return self.rf_ms <= RF_LIMIT_MS

    @property
    def within_limit(self) -> bool:
        return self.total_ms <= E2E_LIMIT_MS

    @property
    def flagged(self) -> bool:
        """True when the configuration must be rejected at mission planning."""
        return not (self.within_limit and self.rf_within_limit)


def rf_hop_ms(range_km: float, interleaver_depth: int) -> float:
    propagation = range_km / SPEED_OF_LIGHT_KM_PER_MS
    framing = FRAME_BASE_MS + FRAME_PER_INTERLEAVER_ROW_MS * interleaver_depth
    return propagation + framing + MODEM_FIXED_MS


def rf_segment_ms(config: LinkConfig) -> float:
    if config.relay:
        hop = rf_hop_ms(config.range_km / 2.0, config.interleaver_depth)
        return 2.0 * hop + RELAY_STORE_FORWARD_MS
    return rf_hop_ms(config.range_km, config.interleaver_depth)


def compute_budget(config: LinkConfig) -> LatencyBudget:
    return LatencyBudget(
        config=config,
        gcs_ms=GCS_SERIALIZATION_MS,
        ground_terminal_ms=GROUND_TERMINAL_MS,
        rf_ms=rf_segment_ms(config),
        air_vehicle_ms=AIR_VEHICLE_RADIO_MS,
    )
