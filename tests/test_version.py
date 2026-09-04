"""Tests for version module."""

from dazzle_claude_config._version import (
    MAJOR, MINOR, PATCH, PHASE, PROJECT_PHASE,
    get_version, get_base_version, get_display_version, get_pip_version,
    __app_name__,
)


def test_app_name():
    assert __app_name__ == "dazzle-claude-config"


def test_version_components():
    assert isinstance(MAJOR, int)
    assert isinstance(MINOR, int)
    assert isinstance(PATCH, int)


def test_phase_valid():
    """PHASE is empty string (stable release) or a string like 'alpha', 'beta', 'rc1'."""
    assert isinstance(PHASE, str)


def test_get_version_returns_string():
    v = get_version()
    assert isinstance(v, str)
    assert len(v) > 0


def test_base_version_format():
    base = get_base_version()
    assert base.startswith(f"{MAJOR}.{MINOR}.{PATCH}")


def test_display_version_includes_project_phase():
    display = get_display_version()
    if PROJECT_PHASE and PROJECT_PHASE != "stable":
        assert PROJECT_PHASE.upper() in display
    else:
        assert display == get_base_version()


def test_pip_version_pep440():
    pip_v = get_pip_version()
    assert "-" not in pip_v
    if PHASE:
        assert any(c.isalpha() for c in pip_v.split(".")[-1])
    else:
        # On main the hook's line yields the bare release ("0.5.20"); on any
        # other branch it yields a PEP 440 dev pre-release ("0.5.20.dev54"),
        # and a branch name with hyphens must never leak into it. Measured
        # 2026-09-03 on branch ccs-ai-pass-1: the old digits-and-dots-only
        # assertion encoded "the suite only runs on main".
        core, _, dev = pip_v.partition(".dev")
        assert all(c.isdigit() or c == "." for c in core), pip_v
        assert dev == "" or dev.isdigit(), pip_v
