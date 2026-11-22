"""Configuration sweep (Flow TES-45254): every *planned* link configuration must
stay within 250 ms end to end and 120 ms RF. A failing case here flags
REQ-45162 / REQ-45148 in Flow."""
import pytest

from dominion_ci import LinkConfig, compute_budget

RANGES_KM = [25, 50, 100, 150, 200]
DEPTHS = [4, 8, 16]

PLANNED = [LinkConfig(f"LOS {r} km / interleaver {d}", r, d) for r in RANGES_KM for d in DEPTHS]
PLANNED += [LinkConfig(f"Relay {r} km / interleaver 4", r, 4, relay=True) for r in (150, 200, 300, 400, 500)]
# Intentionally failing planned configuration for the demo: the Inuvik relay
# corridor was planned with interleaver depth 8, which pushes the RF segment to
# ~146 ms and the end-to-end budget to ~260 ms.
PLANNED += [LinkConfig("Inuvik relay corridor 300 km / interleaver 4", 300, 4, relay=True)]


@pytest.mark.flow(test_case="TES-45254", requirements=["REQ-45162", "REQ-45148"])
@pytest.mark.parametrize("config", PLANNED, ids=[c.name for c in PLANNED])
def test_planned_configuration_within_budget(config, flow_measure):
    b = compute_budget(config)
    flow_measure(round(b.total_ms, 1))
    assert b.rf_within_limit, f"RF segment {b.rf_ms:.1f} ms > 120 ms"
    assert b.within_limit, f"end-to-end {b.total_ms:.1f} ms > 250 ms"
