"""Unit tests for core domain constants."""

import pytest

from src.core.domain.disclaimer import CLINICAL_SAFETY_DISCLAIMER

pytestmark = pytest.mark.unit


def test_disclaimer_is_advisory() -> None:
    assert "informational only" in CLINICAL_SAFETY_DISCLAIMER
    assert "clinician" in CLINICAL_SAFETY_DISCLAIMER
