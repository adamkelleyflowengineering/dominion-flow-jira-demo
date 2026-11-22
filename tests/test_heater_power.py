import pytest

from dominion_ci import heater_power_command
from dominion_ci.heater_power import MAX_KW, MIN_ICING_KW, STANDBY_KW

pytestmark = pytest.mark.flow(test_case="TES-45257", requirements=["REQ-45163"])


def test_minimum_power_in_light_warm_icing():
    assert heater_power_command(5, 0.0, True) == pytest.approx(MIN_ICING_KW)


def test_maximum_power_in_severe_cold_icing(flow_measure):
    p = heater_power_command(-40, 1.0, True)
    flow_measure(p)
    assert p == pytest.approx(MAX_KW)


def test_standby_when_no_icing():
    assert heater_power_command(-20, 0.5, False) == STANDBY_KW


def test_power_never_exceeds_bus_limit_with_out_of_range_inputs():
    assert heater_power_command(-60, 3.0, True) <= MAX_KW


def test_more_water_means_more_power():
    assert heater_power_command(-10, 0.8, True) > heater_power_command(-10, 0.2, True)


def test_negative_lwc_rejected():
    with pytest.raises(ValueError):
        heater_power_command(-10, -0.1, True)
