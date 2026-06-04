"""Tests for the RL trading environment and agent (Phase 5.D.4).

Test strategy
-------------
* TradingEnvConfig -- config dataclass validation (bad and good inputs).
* TradingEnv API correctness -- gymnasium.utils.env_checker.check_env passes;
  reset returns (obs, info); step returns the 5-tuple with correct types and
  shapes; episode terminates at the end of the price path.
* Reward correctness on a KNOWN price path:
  - Holding LONG on a monotonically rising path earns positive cumulative reward.
  - Holding SHORT on a monotonically rising path earns negative cumulative reward.
  - A position flip incurs the documented transaction-cost penalty.
* Determinism -- same seed + same actions -> identical reward sequence.
* Feature window and padding -- observation shape and zero-padding at the start
  of an episode.
* RLAgentConfig -- config dataclass validation.
* RLTradingAgent smoke train -- train(total_timesteps=500) runs end-to-end
  and predict returns a valid action in {0, 1, 2}. Does NOT assert profitability.
* save / load round-trip -- saved policy produces the same action as the
  original on the same observation.
* Lazy-import ImportError path -- module-level sentinel works without gymnasium.

Note on lazy-import tests: torch (pulled in by stable_baselines3) performs a
DLL integrity check at import. Patching sys.modules or importing torch at test
module level causes a Windows access violation when pytest's assertion rewriter
re-executes the import. The lazy-import tests therefore use
builtins.__import__ patching, which intercepts the import call before touching
sys.modules or DLLs, and do NOT pre-import torch or stable_baselines3 at
module scope.
"""
from __future__ import annotations

import builtins
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from core_trading.signals.ml.rl import (
    RLAgentConfig,
    RLTradingAgent,
    TradingEnv,
    TradingEnvConfig,
)
from core_trading.signals.ml.rl.environment import TradingEnv as _TradingEnvDirect

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rising_prices(n: int = 60, step: float = 0.01) -> np.ndarray:
    """Monotonically rising price path: p[t] = 100 * (1 + step)^t."""
    return 100.0 * (1.0 + step) ** np.arange(n, dtype=np.float64)


def _flat_prices(n: int = 60) -> np.ndarray:
    """Constant price path: p[t] = 100 for all t."""
    return np.full(n, 100.0, dtype=np.float64)


def _make_env(
    n: int = 30,
    window_size: int = 3,
    cost_pct: float = 0.001,
    eta: float = 0.1,
    step: float = 0.01,
) -> TradingEnv:
    cfg = TradingEnvConfig(window_size=window_size, cost_pct=cost_pct, eta=eta)
    return TradingEnv(prices=_rising_prices(n, step=step), config=cfg)


# ---------------------------------------------------------------------------
# TradingEnvConfig validation
# ---------------------------------------------------------------------------


class TestTradingEnvConfig:
    def test_defaults_valid(self) -> None:
        cfg = TradingEnvConfig()
        assert cfg.window_size == 5
        assert cfg.cost_pct == 0.001
        assert cfg.eta == 0.01
        assert cfg.obs_clip == 10.0

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"window_size": 0}, "window_size must be >= 1"),
            ({"cost_pct": -0.1}, "cost_pct must be in"),
            ({"cost_pct": 1.0}, "cost_pct must be in"),
            ({"eta": 0.0}, "eta must be in"),
            ({"eta": 1.0}, "eta must be in"),
            ({"obs_clip": 0.0}, "obs_clip must be > 0"),
            ({"obs_clip": -1.0}, "obs_clip must be > 0"),
        ],
    )
    def test_validation(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            TradingEnvConfig(**kwargs)

    @pytest.mark.parametrize("window_size", [1, 2, 10])
    def test_window_size_accepted(self, window_size: int) -> None:
        cfg = TradingEnvConfig(window_size=window_size)
        assert cfg.window_size == window_size

    def test_zero_cost_accepted(self) -> None:
        cfg = TradingEnvConfig(cost_pct=0.0)
        assert cfg.cost_pct == 0.0


# ---------------------------------------------------------------------------
# TradingEnv -- gymnasium API correctness
# ---------------------------------------------------------------------------


class TestTradingEnvAPI:
    def test_check_env_passes(self) -> None:
        """gymnasium.utils.env_checker.check_env must pass with no warnings."""
        import warnings

        from gymnasium.utils.env_checker import check_env

        env = _make_env()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            check_env(env, skip_render_check=True)
        assert len(w) == 0, f"check_env emitted unexpected warnings: {w}"

    def test_reset_returns_obs_and_info(self) -> None:
        env = _make_env(window_size=3)
        result = env.reset(seed=0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        obs, info = result
        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32
        # window_size=3, 1 feature (log return) -> obs size 3
        assert obs.shape == (3,)
        assert isinstance(info, dict)

    def test_step_returns_five_tuple(self) -> None:
        env = _make_env()
        env.reset(seed=0)
        result = env.step(2)
        assert len(result) == 5
        obs, reward, terminated, truncated, info = result
        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)

    def test_truncated_always_false(self) -> None:
        env = _make_env(n=10)
        env.reset()
        for _ in range(9):
            _, _, terminated, truncated, _ = env.step(1)
            assert not truncated

    def test_episode_terminates_at_end_of_path(self) -> None:
        """The episode must terminate exactly when the price path is exhausted."""
        n = 15
        env = _make_env(n=n, window_size=2)
        env.reset()
        # n-1 steps to exhaust an n-price path.
        n_steps = n - 1
        terminated = False
        for i in range(n_steps):
            _, _, terminated, truncated, _ = env.step(1)
            if i < n_steps - 1:
                assert not terminated, f"terminated early at step {i}"
            assert not truncated
        assert terminated, "episode did not terminate at end of path"

    def test_obs_shape_consistent_after_multiple_steps(self) -> None:
        env = _make_env(window_size=4)
        obs, _ = env.reset()
        expected_shape = obs.shape
        for _ in range(5):
            obs, _, terminated, _, _ = env.step(1)
            assert obs.shape == expected_shape
            if terminated:
                break

    def test_obs_in_observation_space(self) -> None:
        env = _make_env()
        obs, _ = env.reset()
        assert env.observation_space.contains(obs)
        for _ in range(5):
            obs, _, terminated, _, _ = env.step(2)
            assert env.observation_space.contains(obs)
            if terminated:
                break

    def test_step_after_done_raises(self) -> None:
        n = 5
        env = _make_env(n=n, window_size=1)
        env.reset()
        for _ in range(n - 1):
            env.step(1)
        with pytest.raises(RuntimeError, match="terminated"):
            env.step(1)

    def test_info_dict_keys(self) -> None:
        env = _make_env()
        env.reset()
        _, _, _, _, info = env.step(2)
        expected_keys = {"position", "raw_return", "transaction_cost", "dsr_A", "dsr_B"}
        assert set(info.keys()) == expected_keys


# ---------------------------------------------------------------------------
# TradingEnv -- reward correctness on known paths
# ---------------------------------------------------------------------------


class TestRewardCorrectness:
    """Verify reward properties on hand-constructed price paths.

    These are the "textbook" checks required by the DOD.
    """

    def _run_episode(
        self, env: TradingEnv, action: int
    ) -> tuple[float, float]:
        """Run a full episode with a constant action; return (total_raw, total_reward)."""
        env.reset(seed=0)
        total_raw = 0.0
        total_reward = 0.0
        terminated = False
        while not terminated:
            _, reward, terminated, _, info = env.step(action)
            total_raw += float(info["raw_return"])
            total_reward += reward
        return total_raw, total_reward

    def test_long_on_rising_path_earns_positive_reward(self) -> None:
        """Holding LONG on a monotonically rising price path must yield positive
        cumulative reward (the basic directional sanity check)."""
        cfg = TradingEnvConfig(window_size=1, cost_pct=0.0, eta=0.1)
        env = TradingEnv(prices=_rising_prices(50, step=0.01), config=cfg)
        total_raw, total_reward = self._run_episode(env, action=2)  # 2 = long
        assert total_raw > 0.0, "long on rising path must yield positive raw return"
        assert total_reward > 0.0, "long on rising path must yield positive DSR reward"

    def test_short_on_rising_path_earns_negative_reward(self) -> None:
        """Holding SHORT on a monotonically rising price path must yield negative
        cumulative reward."""
        cfg = TradingEnvConfig(window_size=1, cost_pct=0.0, eta=0.1)
        env = TradingEnv(prices=_rising_prices(50, step=0.01), config=cfg)
        total_raw, total_reward = self._run_episode(env, action=0)  # 0 = short
        assert total_raw < 0.0, "short on rising path must yield negative raw return"
        assert total_reward < 0.0, "short on rising path must yield negative DSR reward"

    def test_transaction_cost_reduces_raw_return(self) -> None:
        """The transaction-cost penalty must reduce the raw return compared with
        a zero-cost episode."""
        prices = _rising_prices(20, step=0.01)
        cfg_free = TradingEnvConfig(window_size=1, cost_pct=0.0, eta=0.1)
        cfg_paid = TradingEnvConfig(window_size=1, cost_pct=0.01, eta=0.1)
        env_free = TradingEnv(prices=prices, config=cfg_free)
        env_paid = TradingEnv(prices=prices, config=cfg_paid)
        raw_free, _ = self._run_episode(env_free, action=2)
        raw_paid, _ = self._run_episode(env_paid, action=2)
        assert raw_paid < raw_free, "positive cost_pct must reduce raw return"

    def test_position_flip_incurs_exact_transaction_cost(self) -> None:
        """A position flip from long (+1) to short (-1) is a delta of 2.0, so
        the transaction cost must be exactly ``2 * cost_pct``."""
        cost_pct = 0.005
        cfg = TradingEnvConfig(window_size=1, cost_pct=cost_pct, eta=0.1)
        prices = _flat_prices(10)  # flat so log_ret = 0; only cost shows
        env = TradingEnv(prices=prices, config=cfg)
        env.reset(seed=0)

        # Step 1: take long (action=2); position changes from 0 to +1.
        # delta = |1 - 0| = 1; cost = cost_pct.
        _, _, _, _, info1 = env.step(2)
        expected_cost1 = cost_pct * 1.0
        assert info1["transaction_cost"] == pytest.approx(expected_cost1)

        # Step 2: flip to short (action=0); position changes from +1 to -1.
        # delta = |(-1) - 1| = 2; cost = 2 * cost_pct.
        _, _, _, _, info2 = env.step(0)
        expected_cost2 = cost_pct * 2.0
        assert info2["transaction_cost"] == pytest.approx(expected_cost2)

    def test_flat_position_on_flat_path_zero_raw_return(self) -> None:
        """Holding FLAT (action=1) on a constant price path earns zero raw return
        regardless of transaction costs (no position change from step to step)."""
        cfg = TradingEnvConfig(window_size=1, cost_pct=0.01, eta=0.1)
        env = TradingEnv(prices=_flat_prices(20), config=cfg)
        env.reset(seed=0)
        terminated = False
        while not terminated:
            _, _, terminated, _, info = env.step(1)
            assert info["raw_return"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# TradingEnv -- determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_same_rewards(self) -> None:
        """Identical seed + identical action sequence must produce identical rewards."""
        prices = _rising_prices(30, step=0.005)
        cfg = TradingEnvConfig(window_size=3, cost_pct=0.001, eta=0.05)
        actions = [2, 2, 0, 1, 2, 0, 1, 1, 2, 0] * 3  # repeat

        def _collect_rewards(seed: int) -> list[float]:
            env = TradingEnv(prices=prices, config=cfg)
            env.reset(seed=seed)
            rewards = []
            for a in actions[: prices.shape[0] - 1]:
                _, r, terminated, _, _ = env.step(a)
                rewards.append(r)
                if terminated:
                    break
            return rewards

        r1 = _collect_rewards(seed=7)
        r2 = _collect_rewards(seed=7)
        np.testing.assert_array_equal(r1, r2)

    def test_different_seeds_same_rewards_on_deterministic_data(self) -> None:
        """The environment reward trajectory is fully determined by the price path
        and action sequence; seed only affects numpy RNG state (not used in step).
        Two different seeds on the same price path with the same actions must
        yield identical rewards because no stochastic path is involved."""
        prices = _rising_prices(20)
        cfg = TradingEnvConfig(window_size=2, cost_pct=0.001, eta=0.05)
        actions = [2] * 19

        def _collect(seed: int) -> list[float]:
            env = TradingEnv(prices=prices, config=cfg)
            env.reset(seed=seed)
            rewards = []
            for a in actions:
                _, r, terminated, _, _ = env.step(a)
                rewards.append(r)
                if terminated:
                    break
            return rewards

        np.testing.assert_array_equal(_collect(seed=1), _collect(seed=99))


# ---------------------------------------------------------------------------
# TradingEnv -- observation window and zero-padding
# ---------------------------------------------------------------------------


class TestObservationWindow:
    def test_initial_obs_is_zero_padded(self) -> None:
        """At step 0, only one feature row is available; the remainder of the
        window must be zero-padded."""
        window_size = 5
        cfg = TradingEnvConfig(window_size=window_size, cost_pct=0.0, eta=0.1)
        prices = _rising_prices(20)
        env = TradingEnv(prices=prices, config=cfg)
        obs, _ = env.reset()
        # The initial features[0] is always zero (prepended zero row for
        # alignment). The first step brings features[1] into view.  After
        # reset the window covers indices 0..0 plus 4 padding zeros.
        # All should be zero or near-zero clipped log-return.
        assert obs.shape == (window_size,)
        # The last 4 rows of the window are pure padding zeros; only index 4
        # (the most recent = features[0]) may be non-zero, but features[0] is
        # always the zero-prepend row, so the entire initial obs is zero.
        np.testing.assert_array_equal(obs, np.zeros(window_size, dtype=np.float32))

    def test_obs_clips_large_features(self) -> None:
        """Features larger than obs_clip must be clipped to [-obs_clip, obs_clip]."""
        obs_clip = 2.0
        cfg = TradingEnvConfig(window_size=1, cost_pct=0.0, eta=0.1, obs_clip=obs_clip)
        # Giant price spike: ratio 1e6 -> log return >> obs_clip.
        prices = np.array([1.0, 1e6], dtype=np.float64)
        env = TradingEnv(prices=prices, config=cfg)
        env.reset()
        # After one step the window includes the huge log return.
        obs, _, _, _, _ = env.step(2)
        assert float(obs[0]) == pytest.approx(obs_clip)

    def test_custom_features_shape(self) -> None:
        """When features are supplied, obs size is window_size * n_features."""
        n = 20
        n_features = 3
        window_size = 4
        prices = _rising_prices(n)
        feats = np.random.RandomState(0).randn(n, n_features).astype(np.float32)
        cfg = TradingEnvConfig(window_size=window_size)
        env = TradingEnv(prices=prices, features=feats, config=cfg)
        obs, _ = env.reset()
        assert obs.shape == (window_size * n_features,)


# ---------------------------------------------------------------------------
# TradingEnv -- input validation
# ---------------------------------------------------------------------------


class TestTradingEnvValidation:
    def test_prices_too_short(self) -> None:
        cfg = TradingEnvConfig(window_size=5)
        with pytest.raises(ValueError, match="window_size\\+1"):
            TradingEnv(prices=np.ones(5), config=cfg)  # need at least 6

    def test_prices_must_be_1d(self) -> None:
        with pytest.raises(ValueError, match="1-D"):
            TradingEnv(prices=np.ones((5, 2)))

    def test_features_must_be_2d(self) -> None:
        prices = _rising_prices(20)
        with pytest.raises(ValueError, match="2-D"):
            TradingEnv(prices=prices, features=np.ones(20))

    def test_features_length_mismatch(self) -> None:
        prices = _rising_prices(20)
        with pytest.raises(ValueError, match="match"):
            TradingEnv(prices=prices, features=np.ones((10, 2), dtype=np.float32))


# ---------------------------------------------------------------------------
# RLAgentConfig validation
# ---------------------------------------------------------------------------


class TestRLAgentConfig:
    def test_defaults_valid(self) -> None:
        cfg = RLAgentConfig()
        assert cfg.algorithm == "PPO"
        assert cfg.policy == "MlpPolicy"
        assert cfg.net_arch == [64, 64]
        assert cfg.seed == 0
        assert cfg.batch_size == 64

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"algorithm": "A2C"}, "algorithm must be"),
            ({"policy": ""}, "policy must be"),
            ({"net_arch": [0, 64]}, "net_arch layer sizes"),
            ({"n_steps": 0}, "n_steps must be"),
            ({"batch_size": 0}, "batch_size must be"),
        ],
    )
    def test_validation(self, kwargs: dict, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            RLAgentConfig(**kwargs)

    def test_dqn_accepted(self) -> None:
        cfg = RLAgentConfig(algorithm="DQN")
        assert cfg.algorithm == "DQN"


# ---------------------------------------------------------------------------
# RLTradingAgent -- smoke train (PPO)
# ---------------------------------------------------------------------------


class TestRLTradingAgentSmokePPO:
    """Smoke-test: train(500) runs end-to-end; predict returns valid action.

    Does NOT assert profitability -- an agent will not converge to alpha
    on tiny synthetic data in a few hundred steps.
    """

    def _make_agent(self) -> tuple[TradingEnv, RLTradingAgent]:
        prices = _rising_prices(80, step=0.005)
        cfg_env = TradingEnvConfig(window_size=3, cost_pct=0.001, eta=0.05)
        env = TradingEnv(prices=prices, config=cfg_env)
        cfg_agent = RLAgentConfig(
            algorithm="PPO",
            net_arch=[32, 32],
            seed=0,
            env_seed=0,
            n_steps=64,
            batch_size=32,
        )
        agent = RLTradingAgent(env=env, config=cfg_agent)
        return env, agent

    def test_not_trained_before_train(self) -> None:
        _, agent = self._make_agent()
        assert not agent.trained

    def test_smoke_train_runs_and_action_is_valid(self) -> None:
        env, agent = self._make_agent()
        agent.train(total_timesteps=500)
        assert agent.trained
        obs, _ = env.reset()
        action = agent.predict(obs)
        assert action in {0, 1, 2}

    def test_predict_before_train_raises(self) -> None:
        env, agent = self._make_agent()
        obs, _ = env.reset()
        with pytest.raises(RuntimeError, match="not trained"):
            agent.predict(obs)

    def test_invalid_total_timesteps_raises(self) -> None:
        _, agent = self._make_agent()
        with pytest.raises(ValueError, match="total_timesteps"):
            agent.train(total_timesteps=0)


# ---------------------------------------------------------------------------
# RLTradingAgent -- smoke train (DQN)
# ---------------------------------------------------------------------------


class TestRLTradingAgentSmokeDQN:
    def test_dqn_smoke_train(self) -> None:
        prices = _rising_prices(80, step=0.005)
        cfg_env = TradingEnvConfig(window_size=3, cost_pct=0.001, eta=0.05)
        env = TradingEnv(prices=prices, config=cfg_env)
        cfg_agent = RLAgentConfig(
            algorithm="DQN",
            net_arch=[32, 32],
            seed=0,
            env_seed=0,
            batch_size=32,
        )
        agent = RLTradingAgent(env=env, config=cfg_agent)
        agent.train(total_timesteps=500)
        obs, _ = env.reset()
        action = agent.predict(obs)
        assert action in {0, 1, 2}


# ---------------------------------------------------------------------------
# RLTradingAgent -- save / load round-trip
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_load_produces_same_action(self) -> None:
        prices = _rising_prices(80, step=0.005)
        cfg_env = TradingEnvConfig(window_size=3, cost_pct=0.001, eta=0.05)
        env = TradingEnv(prices=prices, config=cfg_env)
        cfg_agent = RLAgentConfig(
            algorithm="PPO",
            net_arch=[32, 32],
            seed=42,
            env_seed=0,
            n_steps=64,
            batch_size=32,
        )
        agent = RLTradingAgent(env=env, config=cfg_agent)
        agent.train(total_timesteps=500)

        obs, _ = env.reset()
        original_action = agent.predict(obs)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "model"
            agent.save(save_path)

            agent2 = RLTradingAgent(env=env, config=cfg_agent)
            agent2.load(save_path)
            loaded_action = agent2.predict(obs)

        assert loaded_action == original_action

    def test_dqn_save_load_produces_same_action(self) -> None:
        """The DQN branch of load() restores a policy that predicts the same
        greedy action as the original (mirrors the PPO round-trip test)."""
        prices = _rising_prices(80, step=0.005)
        cfg_env = TradingEnvConfig(window_size=3, cost_pct=0.001, eta=0.05)
        env = TradingEnv(prices=prices, config=cfg_env)
        cfg_agent = RLAgentConfig(
            algorithm="DQN",
            net_arch=[32, 32],
            seed=42,
            env_seed=0,
            batch_size=32,
        )
        agent = RLTradingAgent(env=env, config=cfg_agent)
        agent.train(total_timesteps=300)

        obs, _ = env.reset()
        original_action = agent.predict(obs)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "model"
            agent.save(save_path)

            agent2 = RLTradingAgent(env=env, config=cfg_agent)
            agent2.load(save_path)
            loaded_action = agent2.predict(obs)

        assert loaded_action == original_action

    def test_save_before_train_raises(self) -> None:
        prices = _rising_prices(30)
        env = TradingEnv(prices=prices)
        agent = RLTradingAgent(env=env)
        with pytest.raises(RuntimeError, match="not trained"):
            agent.save("/tmp/model")


# ---------------------------------------------------------------------------
# Config property accessors
# ---------------------------------------------------------------------------


class TestConfigProperties:
    def test_env_config_property_returns_supplied_config(self) -> None:
        cfg = TradingEnvConfig(window_size=3)
        env = TradingEnv(prices=_rising_prices(30), config=cfg)
        assert env.config is cfg

    def test_agent_config_property_returns_supplied_config(self) -> None:
        env = TradingEnv(prices=_rising_prices(30))
        cfg = RLAgentConfig(seed=7)
        agent = RLTradingAgent(env=env, config=cfg)
        assert agent.config is cfg


# ---------------------------------------------------------------------------
# Lazy-import / sentinel path
# ---------------------------------------------------------------------------

class TestLazyImport:
    def test_import_error_when_gymnasium_absent(self) -> None:
        """When gymnasium is not importable, reloading the environment module
        sets _GYM_AVAILABLE=False and the sentinel TradingEnv raises ImportError.

        Uses builtins.__import__ patching rather than sys.modules manipulation
        to avoid triggering the torch DLL reload crash on Windows (see module
        docstring note above).
        """
        import importlib

        import core_trading.signals.ml.rl.environment as env_mod

        real_import = builtins.__import__

        def _no_gym(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "gymnasium" or name.startswith("gymnasium."):
                raise ModuleNotFoundError("No module named 'gymnasium' (test mock)")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_gym):
            importlib.reload(env_mod)
            with pytest.raises(ImportError, match="gymnasium"):
                env_mod.TradingEnv(prices=np.ones(10))

        # Restore the real implementation.
        importlib.reload(env_mod)

    def test_import_error_when_sb3_absent(self) -> None:
        """When stable_baselines3 is not importable, RLTradingAgent.train()
        raises ImportError (lazy-import pattern: SB3 is imported inside the
        method, not at module level).

        Uses builtins.__import__ patching to intercept the lazy import call
        inside train() without triggering the torch DLL reload issue. Note:
        since stable_baselines3 and torch are already in sys.modules when this
        test runs (they were pre-imported before pytest.main()), the patch
        catches the SB3 import *name* lookup before sys.modules is checked.

        Implementation detail: Python's import system checks sys.modules
        BEFORE calling __import__, so builtins patching alone does not intercept
        cached modules. We therefore temporarily remove SB3 submodules from
        sys.modules during the patch window so the patched __import__ is
        actually invoked.
        """
        import sys

        prices = _rising_prices(30)
        env = TradingEnv(prices=prices)
        agent = RLTradingAgent(env=env)

        real_import = builtins.__import__

        def _no_sb3(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "stable_baselines3" or name.startswith("stable_baselines3."):
                raise ModuleNotFoundError(
                    "No module named 'stable_baselines3' (test mock)"
                )
            return real_import(name, *args, **kwargs)

        # Temporarily evict stable_baselines3 from sys.modules so the
        # patched __import__ is triggered (Python skips __import__ for
        # already-cached modules).
        sb3_keys = [k for k in sys.modules if k == "stable_baselines3" or k.startswith("stable_baselines3.")]
        saved = {k: sys.modules.pop(k) for k in sb3_keys}
        try:
            with (
                patch("builtins.__import__", side_effect=_no_sb3),
                pytest.raises(ImportError, match="stable_baselines3"),
            ):
                agent.train(total_timesteps=10)
        finally:
            # Restore sys.modules so subsequent tests can use SB3.
            sys.modules.update(saved)

    def test_import_error_when_sb3_absent_on_load(self) -> None:
        """RLTradingAgent.load() raises ImportError when stable_baselines3 is
        not importable (same lazy-import contract as train())."""
        import sys

        prices = _rising_prices(30)
        env = TradingEnv(prices=prices)
        agent = RLTradingAgent(env=env)

        real_import = builtins.__import__

        def _no_sb3(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "stable_baselines3" or name.startswith("stable_baselines3."):
                raise ModuleNotFoundError(
                    "No module named 'stable_baselines3' (test mock)"
                )
            return real_import(name, *args, **kwargs)

        sb3_keys = [
            k
            for k in sys.modules
            if k == "stable_baselines3" or k.startswith("stable_baselines3.")
        ]
        saved = {k: sys.modules.pop(k) for k in sb3_keys}
        try:
            with (
                patch("builtins.__import__", side_effect=_no_sb3),
                pytest.raises(ImportError, match="stable_baselines3"),
            ):
                agent.load("nonexistent_model")
        finally:
            # Restore sys.modules so subsequent tests can use SB3.
            sys.modules.update(saved)


# ---------------------------------------------------------------------------
# Public API re-exports from __init__.py
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_all_exports(self) -> None:
        from core_trading.signals.ml import rl as rl_pkg

        assert hasattr(rl_pkg, "TradingEnvConfig")
        assert hasattr(rl_pkg, "TradingEnv")
        assert hasattr(rl_pkg, "RLAgentConfig")
        assert hasattr(rl_pkg, "RLTradingAgent")

    def test_trading_env_direct_import(self) -> None:
        assert _TradingEnvDirect is TradingEnv
