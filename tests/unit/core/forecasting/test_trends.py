"""Unit tests for the pure-Python trend (least-squares) estimator."""

from __future__ import annotations

import pytest

from src.core.forecasting.trends import compute_channel_slope

pytestmark = pytest.mark.unit


class TestLeastSquares:
    def test_two_points(self) -> None:
        # 1 hour apart, +10 per hour.
        slope = compute_channel_slope([0.0, 3600.0], [10.0, 20.0])
        assert slope == 10.0

    def test_three_points(self) -> None:
        # values rise +10 per hour -> slope 10.0 per hour.
        t = [0.0, 3600.0, 7200.0]
        v = [0.0, 10.0, 20.0]
        assert compute_channel_slope(t, v) == 10.0

    def test_ten_points(self) -> None:
        t = [i * 3600.0 for i in range(10)]
        v = [5.0 + i for i in range(10)]  # +1 per hour
        assert compute_channel_slope(t, v) == 1.0

    def test_negative_slope(self) -> None:
        assert compute_channel_slope([0.0, 3600.0], [20.0, 5.0]) == -15.0


class TestEdgeCases:
    def test_fewer_than_two_points_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_channel_slope([0.0], [1.0])

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            compute_channel_slope([0.0, 1.0], [1.0])

    def test_zero_variance_returns_zero(self) -> None:
        # All timestamps identical -> denom == 0 -> baseline returns 0.0.
        assert compute_channel_slope([1.0, 1.0, 1.0], [10.0, 20.0, 30.0]) == 0.0


class TestSparseNulls:
    def test_none_values_filtered_by_caller(self) -> None:
        # The estimator is pure stats; the caller (ClinicalAssessmentService)
        # filters None channels before invoking. Simulate a sparse series where
        # one mid observation had no reading for the channel.
        t_full = [0.0, 1800.0, 3600.0]
        v_full = [0.0, None, 20.0]  # type: ignore[list-item]
        # Caller keeps only non-None pairs -> equivalent to t=[0,3600], v=[0,20].
        t_filtered = [t for t, v in zip(t_full, v_full) if v is not None]
        v_filtered = [v for v in v_full if v is not None]
        # 0 -> 20 over 1 hour -> 20.0 per hour.
        assert compute_channel_slope(t_filtered, v_filtered) == 20.0
