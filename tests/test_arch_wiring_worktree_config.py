"""
kernel/worktree.WORKTREE_ROOT — driven by Settings.worktree_root.

Characterization: WORKTREE_ROOT must equal Path(settings.worktree_root),
not the hardcoded Path("/root/.anima-worktrees") literal. This makes the
worktree root configurable via RAWOS_WORKTREE_ROOT env var for non-Linux
arch backends (Stage B/C). Stage A: default is "/root/.anima-worktrees",
identical to the previous hardcoded value — zero behavior change.
"""
from __future__ import annotations

from pathlib import Path

from anima.config import settings
from anima.kernel.worktree import WORKTREE_ROOT


def test_worktree_root_matches_settings():
    assert WORKTREE_ROOT == Path(settings.worktree_root)


def test_worktree_root_default_is_anima_worktrees():
    assert str(WORKTREE_ROOT) == "/root/.anima-worktrees"
