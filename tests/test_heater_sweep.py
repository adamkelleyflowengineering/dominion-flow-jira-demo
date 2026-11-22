"""Envelope sweep (Flow TES-45259): OAT -40..+5 C x LWC 0..1.0 g/m3 in icing."""
import pytest

from dominion_ci import heater_power_command

OATS = list(range(-40, 6, 5))           # 10 temperatures
LWCS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]   # 6 water contents -> 60 cases


@pytest.mark.flow(test_case="TES-45259", requirements=["REQ-45163"])
@pytest.mark.parametrize("lwc", LWCS)
@pytest.mark.parametrize("oat", OATS)
def test_icing_power_within_limits(oat, lwc, flow_measure):
    p = heater_power_command(oat, lwc, True)
    flow_measure(p)
    assert 2.4 <= p <= 3.0
