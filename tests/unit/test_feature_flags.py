"""Unit tests for libs/common/feature_flags.py.

This module previously contained an indentation syntax error in
FeatureFlag.is_enabled's dependency loop that prevented it from importing at
all. These tests lock the corrected behaviour, with emphasis on the dependency
resolution path that was broken.
"""

import pytest

from libs.common.feature_flags import (
    FeatureFlag,
    FeatureFlags,
    FeatureStatus,
    get_flags,
    is_enabled,
)


class TestFeatureFlagStatusShortCircuits:
    def test_disabled_status_is_false(self):
        flag = FeatureFlag("x", default_value=True, status=FeatureStatus.DISABLED)
        assert flag.is_enabled() is False

    def test_enabled_status_is_true(self):
        flag = FeatureFlag("x", default_value=False, status=FeatureStatus.ENABLED)
        assert flag.is_enabled() is True


class TestFeatureFlagDependencyPath:
    """Exercises the loop whose broken indentation made the module unimportable."""

    def test_dependency_satisfied_returns_value(self):
        flag = FeatureFlag(
            "feat",
            default_value=True,
            status=FeatureStatus.EXPERIMENTAL,
            depends_on=["dep1"],
        )
        assert flag.is_enabled({"feat": True, "dep1": True}) is True

    def test_dependency_unsatisfied_returns_false(self):
        flag = FeatureFlag(
            "feat",
            default_value=True,
            status=FeatureStatus.EXPERIMENTAL,
            depends_on=["dep1"],
        )
        assert flag.is_enabled({"feat": True, "dep1": False}) is False

    def test_missing_dependency_returns_false(self):
        flag = FeatureFlag(
            "feat",
            default_value=True,
            status=FeatureStatus.EXPERIMENTAL,
            depends_on=["dep1"],
        )
        # dep1 absent from the flags map -> treated as falsy -> disabled.
        assert flag.is_enabled({"feat": True}) is False

    def test_multiple_dependencies_all_required(self):
        flag = FeatureFlag(
            "feat",
            default_value=True,
            status=FeatureStatus.EXPERIMENTAL,
            depends_on=["dep1", "dep2"],
        )
        assert flag.is_enabled({"feat": True, "dep1": True, "dep2": True}) is True
        assert flag.is_enabled({"feat": True, "dep1": True, "dep2": False}) is False


class TestFeatureFlagEnvAndDefault:
    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("FEATURE_MY_FLAG", "true")
        flag = FeatureFlag("my_flag", status=FeatureStatus.EXPERIMENTAL)
        assert flag.is_enabled() is True

    def test_env_falsy_value(self, monkeypatch):
        monkeypatch.setenv("FEATURE_MY_FLAG", "off")
        flag = FeatureFlag("my_flag", default_value=True, status=FeatureStatus.EXPERIMENTAL)
        assert flag.is_enabled() is False

    def test_falls_back_to_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FEATURE_MY_FLAG", raising=False)
        flag = FeatureFlag("my_flag", default_value=True, status=FeatureStatus.EXPERIMENTAL)
        assert flag.is_enabled() is True


class TestFeatureFlagsManager:
    def test_known_defaults(self):
        assert FeatureFlags.is_enabled("paper_trading") is True
        assert FeatureFlags.is_enabled("live_trading") is False

    def test_unknown_flag_raises(self):
        with pytest.raises(ValueError, match="Unknown feature flag"):
            FeatureFlags.is_enabled("does_not_exist")

    def test_get_flags_returns_all(self):
        flags = get_flags()
        assert "paper_trading" in flags
        assert flags["paper_trading"]["current_value"] is True

    def test_convenience_is_enabled(self):
        assert is_enabled("paper_trading") is True
