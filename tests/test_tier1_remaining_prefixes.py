"""Tests for _TIER1_PREFIXES entries not covered by existing test files:

- rawos/dataset/  (rawos/dataset/schema.py)
- rawos/study/    (rawos/study/notes.md)
- rawos/timing/   (rawos/timing/benchmark.py)
"""

from anima.kernel.tools import _in_tier1_allowlist


class TestTier1RemainingPrefixes:
    """Verify _in_tier1_allowlist returns True for paths under each
    TIER 1 directory that had no dedicated assertions yet."""

    def test_dataset_prefix(self) -> None:
        assert _in_tier1_allowlist("rawos/dataset/schema.py") is True

    def test_study_prefix(self) -> None:
        assert _in_tier1_allowlist("rawos/study/notes.md") is True

    def test_timing_prefix(self) -> None:
        assert _in_tier1_allowlist("rawos/timing/benchmark.py") is True
