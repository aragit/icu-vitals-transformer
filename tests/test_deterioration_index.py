"""Tests for deterioration index and severity classification."""


from src.governance.deterioration import compute_deterioration_index
from src.governance.severity import severity_from_score
from src.models.vitals import VitalSignsWindow


class TestDeteriorationIndex:
    def test_normal_vitals(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=72,
            systolic_bp=120,
            diastolic_bp=80,
            spo2=98,
            respiratory_rate=16,
            temperature=36.5,
            avpu="A",
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 0
        assert factors == []

    def test_respiratory_rate_critical(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            respiratory_rate=28,
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 3
        assert "respiratory_rate_critical" in factors

    def test_spo2_severe(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            spo2=89,
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 3
        assert "spo2_severe" in factors

    def test_multiple_factors(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=140,
            systolic_bp=85,
            spo2=90,
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 9  # 3 + 3 + 3
        assert len(factors) == 3

    def test_trend_bonus(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=115,
        )
        score, factors = compute_deterioration_index(vitals, trend="rapidly_deteriorating")
        assert score == 4  # 2 + 2
        assert "rapid_deterioration_trend" in factors

    def test_altered_consciousness(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            avpu="V",
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 3
        assert "altered_consciousness_V" in factors

    def test_none_values_ignored(self):
        vitals = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
        )
        score, factors = compute_deterioration_index(vitals)
        assert score == 0
        assert factors == []


class TestSeverityClassification:
    def test_normal(self):
        assert severity_from_score(0) == "NORMAL"
        assert severity_from_score(2) == "NORMAL"

    def test_warning(self):
        assert severity_from_score(3) == "WARNING"
        assert severity_from_score(4) == "WARNING"

    def test_alert(self):
        assert severity_from_score(5) == "ALERT"
        assert severity_from_score(6) == "ALERT"

    def test_emergency(self):
        assert severity_from_score(7) == "EMERGENCY"
        assert severity_from_score(10) == "EMERGENCY"

    def test_critical_trend_overrides(self):
        assert severity_from_score(2, trend="critical") == "EMERGENCY"
