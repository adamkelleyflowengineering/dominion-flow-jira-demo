import pytest

from dominion_ci import LinkConfig, compute_budget
from dominion_ci.latency_budget import E2E_LIMIT_MS, RF_LIMIT_MS, rf_hop_ms

pytestmark = pytest.mark.flow(test_case="TES-45252", requirements=["REQ-45162", "REQ-45141"])


def test_reference_configuration_matches_flow_allocation(flow_measure):
    # 150 km line of sight, interleaver 16 is the design point in Flow (212 ms).
    b = compute_budget(LinkConfig("reference 150 km", 150, 16))
    flow_measure(round(b.total_ms, 1))
    assert b.rf_ms == pytest.approx(98.0, abs=0.6)
    assert b.total_ms == pytest.approx(212.0, abs=0.6)
    assert not b.flagged


def test_budget_is_sum_of_segments():
    b = compute_budget(LinkConfig("x", 80, 8))
    assert b.total_ms == pytest.approx(b.gcs_ms + b.ground_terminal_ms + b.rf_ms + b.air_vehicle_ms)


def test_propagation_increases_with_range():
    assert rf_hop_ms(200, 16) > rf_hop_ms(50, 16)


def test_relay_adds_second_hop_and_store_forward():
    los = compute_budget(LinkConfig("los", 100, 4))
    relay = compute_budget(LinkConfig("relay", 100, 4, relay=True))
    assert relay.rf_ms > los.rf_ms


def test_over_budget_configuration_is_flagged():
    b = compute_budget(LinkConfig("deep interleaver", 150, 32))
    assert b.rf_ms > RF_LIMIT_MS
    assert b.flagged


def test_limits_match_requirements():
    assert E2E_LIMIT_MS == 250.0
    assert RF_LIMIT_MS == 120.0


@pytest.mark.parametrize("kwargs", [
    {"range_km": 0},
    {"range_km": -5},
    {"range_km": 100, "interleaver_depth": 12},
    {"range_km": 400},
])
def test_invalid_configurations_rejected(kwargs):
    with pytest.raises(ValueError):
        LinkConfig("bad", **kwargs)
