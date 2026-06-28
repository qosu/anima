"""Tests for _TIER1_PREFIXES entries not covered by existing test files:

- anima/dataset/  (anima/dataset/schema.py)
- anima/study/    (anima/study/notes.md)
- anima/timing/   (anima/timing/benchmark.py)
"""

from anima.kernel.tools import _in_tier1_allowlist


class TestTier1RemainingPrefixes:
    """Verify _in_tier1_allowlist returns True for paths under each
    TIER 1 directory that had no dedicated assertions yet."""

    def test_dataset_prefix(self) -> None:
        assert _in_tier1_allowlist("anima/dataset/schema.py") is True

    def test_study_prefix(self) -> None:
        assert _in_tier1_allowlist("anima/study/notes.md") is True

    def test_timing_prefix(self) -> None:
        assert _in_tier1_allowlist("anima/timing/benchmark.py") is True
