"""
Phase 16 Pass 2 — TIER enforcement helper tests.

Covers the git-introspection helpers added in rawos/kernel/tools.py that
the execute() wrapper (Pass 2 step b, not yet implemented) will use to
detect and revert TIER 0 violations during self-modification of
/root/rawos. See PLAN.md "Phase 16 — Pass 2 — implementation design".
"""
from __future__ import annotations

import asyncio
import subprocess

import pytest


def _git(*args: str, cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path: str) -> None:
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@rawos.local", cwd=path)
    _git("config", "user.name", "rawos-test", cwd=path)


# ---------------------------------------------------------------------------
# _in_tier1_allowlist — pure function
# ---------------------------------------------------------------------------

class TestInTier1Allowlist:
    def test_tests_dir_allowed(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert _in_tier1_allowlist("tests/test_new_module.py")

    def test_evaluation_dir_allowed(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert _in_tier1_allowlist("rawos/evaluation/metrics.py")

    def test_docs_dir_allowed(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert _in_tier1_allowlist("docs/architecture.md")

    def test_exact_prefix_with_no_trailing_slash_allowed(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert _in_tier1_allowlist("rawos/manifester")

    def test_tier0_api_path_blocked(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert not _in_tier1_allowlist("rawos/api/app.py")

    def test_tier0_kernel_tools_blocked(self):
        from rawos.kernel.tools import _in_tier1_allowlist
        assert not _in_tier1_allowlist("rawos/kernel/tools.py")

    def test_similar_prefix_not_falsely_matched(self):
        # "rawos/studyx/" must NOT match the "rawos/study/" prefix
        from rawos.kernel.tools import _in_tier1_allowlist
        assert not _in_tier1_allowlist("rawos/studyx/evil.py")


# ---------------------------------------------------------------------------
# _diff_paths — pure function
# ---------------------------------------------------------------------------

class TestDiffPaths:
    def test_new_dirty_path_detected(self):
        from rawos.kernel.tools import _diff_paths
        assert _diff_paths({}, {"a.py": "M "}) == {"a.py"}

    def test_unchanged_status_not_flagged(self):
        from rawos.kernel.tools import _diff_paths
        before = {"data/rawos.db": "M "}
        after = {"data/rawos.db": "M "}
        assert _diff_paths(before, after) == set()

    def test_reverted_to_clean_detected(self):
        from rawos.kernel.tools import _diff_paths
        before = {"a.py": "M "}
        after: dict[str, str] = {}
        assert _diff_paths(before, after) == {"a.py"}

    def test_status_change_on_already_dirty_path_detected(self):
        from rawos.kernel.tools import _diff_paths
        before = {"a.py": " M"}
        after = {"a.py": "MM"}
        assert _diff_paths(before, after) == {"a.py"}

    def test_independent_path_untouched(self):
        from rawos.kernel.tools import _diff_paths
        before = {"data/rawos.db": "M "}
        after = {"data/rawos.db": "M ", "rawos/api/app.py": " M"}
        assert _diff_paths(before, after) == {"rawos/api/app.py"}


# ---------------------------------------------------------------------------
# _is_rawos_source_tree — git introspection
# ---------------------------------------------------------------------------

class TestIsRawosSourceTree:
    def test_unrelated_repo_is_not_rawos(self, tmp_path):
        from rawos.kernel.tools import _is_rawos_source_tree
        _init_repo(str(tmp_path))
        assert asyncio.run(_is_rawos_source_tree(str(tmp_path))) is False

    def test_non_git_dir_is_not_rawos(self, tmp_path):
        from rawos.kernel.tools import _is_rawos_source_tree
        assert asyncio.run(_is_rawos_source_tree(str(tmp_path))) is False


# ---------------------------------------------------------------------------
# _git_status_porcelain — git introspection
# ---------------------------------------------------------------------------

class TestGitStatusPorcelain:
    def test_clean_repo_is_empty(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        assert asyncio.run(_git_status_porcelain(str(tmp_path))) == {}

    def test_untracked_file_detected(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        (tmp_path / "new.txt").write_text("new")
        status = asyncio.run(_git_status_porcelain(str(tmp_path)))
        assert status == {"new.txt": "??"}

    def test_modified_tracked_file_detected(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        (tmp_path / "a.txt").write_text("changed")
        status = asyncio.run(_git_status_porcelain(str(tmp_path)))
        assert status == {"a.txt": " M"}

    def test_rename_split_into_two_entries(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain
        _init_repo(str(tmp_path))
        (tmp_path / "old.txt").write_text("a")
        _git("add", "old.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        _git("mv", "old.txt", "new.txt", cwd=str(tmp_path))
        status = asyncio.run(_git_status_porcelain(str(tmp_path)))
        assert status["new.txt"] == "RM" or status["new.txt"][0] == "R"
        assert status["old.txt"] == "D "

    def test_non_git_dir_returns_empty(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain
        assert asyncio.run(_git_status_porcelain(str(tmp_path))) == {}


# ---------------------------------------------------------------------------
# _git_checkout_restore — git introspection, mutates working tree
# ---------------------------------------------------------------------------

class TestGitCheckoutRestore:
    def test_restores_modified_tracked_file(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain, _git_checkout_restore
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("original")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        (tmp_path / "a.txt").write_text("violation")

        asyncio.run(_git_checkout_restore(str(tmp_path), "a.txt"))

        assert (tmp_path / "a.txt").read_text() == "original"
        assert asyncio.run(_git_status_porcelain(str(tmp_path))) == {}

    def test_removes_new_untracked_file(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain, _git_checkout_restore
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        (tmp_path / "evil.py").write_text("malicious")

        asyncio.run(_git_checkout_restore(str(tmp_path), "evil.py"))

        assert not (tmp_path / "evil.py").exists()
        assert asyncio.run(_git_status_porcelain(str(tmp_path))) == {}

    def test_removes_new_staged_file(self, tmp_path):
        from rawos.kernel.tools import _git_status_porcelain, _git_checkout_restore
        _init_repo(str(tmp_path))
        (tmp_path / "a.txt").write_text("a")
        _git("add", "a.txt", cwd=str(tmp_path))
        _git("commit", "-qm", "init", cwd=str(tmp_path))
        (tmp_path / "evil.py").write_text("malicious")
        _git("add", "evil.py", cwd=str(tmp_path))

        asyncio.run(_git_checkout_restore(str(tmp_path), "evil.py"))

        assert not (tmp_path / "evil.py").exists()
        assert asyncio.run(_git_status_porcelain(str(tmp_path))) == {}
