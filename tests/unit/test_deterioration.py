"""Unit tests for governance scoring (baseline contract).

Pin ``src.governance.deterioration`` and ``src.governance.severity``:
NEWS2-inspired scoring with the baseline tiers NORMAL/WARNING/ALERT/EMERGENCY.

Note (baseline): the baseline emits four severity tiers
(NORMAL/WARNING/ALERT/EMERGENCY). The LOW/MEDIUM/HIGH/CRITICAL naming is a
future-state refactor target documented in docs/BASELINE.md §6; this suite
asserts the actual baseline mapping at every score boundary.
"""

import pytest

from src.governance.deterioration import compute_deterioration_index
from src.governance.severity import severity_from_score
from src.models.vitals import VitalSignsWindow

pytestmark = pytest.mark.unit


def _window(**kw) -> VitalSignsWindow:
    defaults = {"patient_id": "PT-001", "window_start": "2026-07-02T08:00:00",
                "window_end": "2026-07-02T08:05:00", "heart_rate": None,
                "systolic_bp": None, "diastolic_bp": None, "spo2": None,
                "respiratory_rate": None, "temperature": None, "avpu": "A"}
    defaults.update(kw)
    return VitalSignsWindow(**defaults)


class TestSeverityTierBoundaries:
    """severity_from_score at every threshold edge: 0, 2, 3, 5, 7, 20."""

    def test_normal_range(self):
        assert severity_from_score(0) == "NORMAL"
        assert severity_from_score(2) == "NORMAL"

    def test_warning_range(self):
        assert severity_from_score(3) == "WARNING"
        assert severity_from_score(4) == "WARNING"

    def test_alert_range(self):
        assert severity_from_score(5) == "ALERT"
        assert severity_from_score(6) == "ALERT"

    def test_emergency_range(self):
        assert severity_from_score(7) == "EMERGENCY"
        assert severity_from_score(20) == "EMERGENCY"

    def test_critical_trend_overrides_low_score(self):
        assert severity_from_score(0, trend="critical") == "EMERGENCY"
        assert severity_from_score(2, trend="critical") == "EMERGENCY"

    def test_stable_trend_does_not_override(self):
        assert severity_from_score(6, trend="stable") == "ALERT"

    def test_baseline_tier_names(self):
        # Baseline contract: four tiers (future refactor: LOW/MEDIUM/HIGH/CRITICAL).
        for s in (0, 3, 5, 7):
            assert severity_from_score(s) in {"NORMAL", "WARNING", "ALERT", "EMERGENCY"}


class TestScoreThresholds:
    """Boundary vital values at each scoring edge."""

    def test_respiratory_rate_boundaries(self):
        assert compute_deterioration_index(_window(respiratory_rate=8))[0] == 0
        assert compute_deterioration_index(_window(respiratory_rate=20))[0] == 0
        score, factors = compute_deterioration_index(_window(respiratory_rate=21))
        assert score == 2
        assert "respiratory_rate_elevated" in factors
        assert compute_deterioration_index(_window(respiratory_rate=25))[0] == 2
        assert compute_deterioration_index(_window(respiratory_rate=26))[0] == 3
        score, factors = compute_deterioration_index(_window(respiratory_rate=26))
        assert "respiratory_rate_critical" in factors
        assert compute_deterioration_index(_window(respiratory_rate=7))[0] == 3

    def test_spo2_boundaries(self):
        assert compute_deterioration_index(_window(spo2=95))[0] == 0
        assert compute_deterioration_index(_window(spo2=94))[0] == 1
        assert "spo2_mild" in compute_deterioration_index(_window(spo2=94))[1]
        assert compute_deterioration_index(_window(spo2=93))[0] == 1
        assert compute_deterioration_index(_window(spo2=92))[0] == 2
        assert compute_deterioration_index(_window(spo2=91))[0] == 2
        assert compute_deterioration_index(_window(spo2=90))[0] == 3
        assert "spo2_severe" in compute_deterioration_index(_window(spo2=90))[1]

    def test_systolic_bp_boundaries(self):
        assert compute_deterioration_index(_window(systolic_bp=100))[0] == 0
        assert compute_deterioration_index(_window(systolic_bp=99))[0] == 2
        assert "systolic_bp_low" in compute_deterioration_index(_window(systolic_bp=99))[1]
        assert compute_deterioration_index(_window(systolic_bp=90))[0] == 2
        assert compute_deterioration_index(_window(systolic_bp=89))[0] == 3
        assert compute_deterioration_index(_window(systolic_bp=220))[0] == 0
        assert compute_deterioration_index(_window(systolic_bp=221))[0] == 3

    def test_heart_rate_boundaries(self):
        assert compute_deterioration_index(_window(heart_rate=40))[0] == 0
        assert compute_deterioration_index(_window(heart_rate=110))[0] == 0
        assert compute_deterioration_index(_window(heart_rate=111))[0] == 2
        assert "heart_rate_elevated" in compute_deterioration_index(_window(heart_rate=111))[1]
        assert compute_deterioration_index(_window(heart_rate=130))[0] == 2
        assert compute_deterioration_index(_window(heart_rate=131))[0] == 3
        assert "heart_rate_critical" in compute_deterioration_index(_window(heart_rate=131))[1]
        assert compute_deterioration_index(_window(heart_rate=39))[0] == 3

    def test_temperature_boundaries(self):
        assert compute_deterioration_index(_window(temperature=35.0))[0] == 0
        assert compute_deterioration_index(_window(temperature=39.0))[0] == 0
        assert compute_deterioration_index(_window(temperature=34.9))[0] == 3
        assert "hypothermia" in compute_deterioration_index(_window(temperature=34.9))[1]
        assert compute_deterioration_index(_window(temperature=39.1))[0] == 2
        assert "hyperthermia" in compute_deterioration_index(_window(temperature=39.1))[1]


class TestAvpuScoring:
    def test_alert_consciousness_scores(self):
        for avpu, label in [("V", "V"), ("P", "P"), ("U", "U")]:
            score, factors = compute_deterioration_index(_window(avpu=avpu))
            assert score == 3
            assert f"altered_consciousness_{label}" in factors

    def test_alert_no_score(self):
        score, factors = compute_deterioration_index(_window(avpu="A"))
        assert score == 0
        assert factors == []


class TestCompositeScores:
    def test_score_zero_healthy(self):
        vitals = _window(heart_rate=72, systolic_bp=120, diastolic_bp=80,
                         spo2=98, respiratory_rate=16, temperature=36.5, avpu="A")
        assert compute_deterioration_index(vitals)[0] == 0

    def test_score_two_single_factor(self):
        assert compute_deterioration_index(_window(heart_rate=115))[0] == 2

    def test_score_three_single_factor(self):
        assert compute_deterioration_index(_window(heart_rate=140))[0] == 3

    def test_score_five_three_factors(self):
        vitals = _window(heart_rate=115, respiratory_rate=22, spo2=94, avpu="A")
        # HR elevated 2 + RR elevated 2 + SpO2 mild 1 = 5
        assert compute_deterioration_index(vitals)[0] == 5
        assert severity_from_score(5) == "ALERT"

    def test_score_seven_three_factors(self):
        vitals = _window(heart_rate=140, respiratory_rate=26, spo2=94, avpu="A")
        # HR critical 3 + RR critical 3 + SpO2 mild 1 = 7
        assert compute_deterioration_index(vitals)[0] == 7
        assert severity_from_score(7) == "EMERGENCY"

    def test_score_twenty_max(self):
        vitals = _window(
            heart_rate=140, systolic_bp=85, spo2=89,
            respiratory_rate=26, temperature=34.0, avpu="V",
        )
        score, factors = compute_deterioration_index(vitals, trend="rapidly_deteriorating")
        # 6 criticals (3 each) + trend 2 = 20
        assert score == 20
        assert severity_from_score(20) == "EMERGENCY"
        assert "rapid_deterioration_trend" in factors

    def test_multiple_factors_collected(self):
        vitals = _window(heart_rate=140, systolic_bp=85, spo2=90,
                         respiratory_rate=28, temperature=39.5, avpu="V")
        score, factors = compute_deterioration_index(vitals)
        # HR critical 3 + SBP critical 3 + SpO2 severe 3 + RR critical 3
        # + hyperthermia 2 + AVPU 3 = 17
        assert score == 17
        assert len(factors) == 6

    def test_none_values_ignored(self):
        score, factors = compute_deterioration_index(_window())
        assert score == 0
        assert factors == []


class TestPropertyLikeInvariants:
    @pytest.mark.property
    def test_severity_monotone_in_score(self):
        # severity rank must never decrease as score increases.
        rank = {"NORMAL": 0, "WARNING": 1, "ALERT": 2, "EMERGENCY": 3}
        prev = -1
        cur = 0
        while cur <= 20:
            r = rank[severity_from_score(cur)]
            assert r >= prev, f"non-monotonic at score={cur}"
            prev = r
            cur += 1

    @pytest.mark.property
    def test_score_non_negative(self):
        for hr in (0, 40, 50, 110, 115, 130, 140, 300):
            score, _ = compute_deterioration_index(_window(heart_rate=hr))
            assert score >= 0
            assert score <= 20
