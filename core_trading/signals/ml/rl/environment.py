"""Reinforcement-learning trading environment (Phase 5.D.4).

Implements a gymnasium ``Env`` for single-instrument directional trading on a
fixed price path. The environment is intentionally **minimal and deterministic**:
its purpose is to serve as the training substrate for :class:`RLTradingAgent`
(see :mod:`core_trading.signals.ml.rl.agent`), not to be a full market simulator.

Action space
------------
**Discrete(3)** is the default: action 0 = short (-1), action 1 = flat (0),
action 2 = long (+1). A discrete action space is compatible with both DQN
(value-based) and PPO (policy-gradient) from stable-baselines3, which makes it
the most versatile choice for a general-purpose RL trading agent. A continuous
action space (Box([-1, 1])) could model fractional sizing but is more sample-
inefficient and harder to tune; discrete is the standard entry point for RL
trading research (cf. Moody & Saffell, 1998).

Observation space
-----------------
A sliding window of ``window_size`` consecutive feature rows, flattened into a
1-D ``Box`` vector. All observations are *clipped* to the configured bounds
before being returned, so the space is always satisfied regardless of raw
feature values.

Reward shaping -- differential Sharpe ratio (Moody-Saffell 1998)
-----------------------------------------------------------------
Raw P&L rewards are extremely noisy and do not penalise variance, leading to
agents that take wild bets. The **differential Sharpe ratio** (DSR) update is
a risk-adjusted online reward from:

    Moody, J. and Saffell, M. (1998). "Optimizing Trading Systems using
    Automated Trading." Proceedings of the 1998 AAAI Spring Symposium on
    Intelligent Adaptive Agents for Financial Modeling.

The DSR tracks exponential moving estimates of the mean and variance of
per-step returns, then delivers the gradient of the Sharpe ratio as the
reward:

    A_t = (1 - eta) * A_{t-1} + eta * r_t        # EMA of returns
    B_t = (1 - eta) * B_{t-1} + eta * r_t^2      # EMA of squared returns

    delta_A = eta * (r_t - A_{t-1})
    delta_B = eta * (r_t^2 - B_{t-1})
    denom   = B_t - A_t^2                         # variance estimate

When ``denom > eps``::

    DSR reward = (B_t * delta_A - 0.5 * A_t * delta_B) / denom^(3/2)

When ``denom <= eps`` (early in the episode, near-zero variance), the DSR
falls back to the raw return ``r_t`` so the agent receives a useful signal
before the Sharpe denominator is meaningful.

Transaction cost
----------------
A penalty of ``cost_pct * |position_change|`` (as a fraction of notional)
is subtracted from the per-step return before computing the DSR reward. This
penalises churn without zeroing rewards on trivial round-trips.

Lazy import of ``gymnasium``
----------------------------
``gymnasium.Env`` must be a base class, so ``gymnasium`` is imported at
module load time. The import is guarded by a try/except: if ``gymnasium`` is
absent, the module is still importable but :class:`TradingEnv` is replaced by
a lightweight sentinel that raises :exc:`ImportError` on instantiation. This
mirrors the pattern used by the other 5.D modules while satisfying the
gymnasium inheritance requirement.

Mathematical references
-----------------------
* Moody, J. and Saffell, M. (1998). "Optimizing Trading Systems using
  Automated Trading." Proc. AAAI-98 Spring Symposium on Intelligent Adaptive
  Agents for Financial Modeling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

try:
    import gymnasium as gym

    _GYM_AVAILABLE = True
except ModuleNotFoundError:
    _GYM_AVAILABLE = False


__all__ = [
    "TradingEnvConfig",
    "TradingEnv",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ACTION_TO_POSITION: dict[int, float] = {0: -1.0, 1: 0.0, 2: 1.0}
"""Map discrete action index to signed position: short / flat / long."""


@dataclass(frozen=True)
class TradingEnvConfig:
    """Hyper-parameters for :class:`TradingEnv`.

    Attributes
    ----------
    window_size:
        Number of consecutive feature rows that form one observation (>= 1).
    cost_pct:
        Proportional transaction-cost penalty on position changes, as a
        fraction of notional (e.g. 0.001 = 10 bps). Must be in ``[0, 1)``.
    eta:
        Exponential smoothing factor for the differential Sharpe reward
        (Moody-Saffell 1998). Must be in ``(0, 1)``. Smaller values give
        smoother estimates; ``0.01`` is a reasonable default.
    obs_clip:
        Symmetric bound for the observation Box space. Features are clipped
        to ``[-obs_clip, obs_clip]`` before being returned. Must be > 0.
    """

    window_size: int = 5
    cost_pct: float = 0.001
    eta: float = 0.01
    obs_clip: float = 10.0

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError("window_size must be >= 1")
        if not 0.0 <= self.cost_pct < 1.0:
            raise ValueError("cost_pct must be in [0, 1)")
        if not 0.0 < self.eta < 1.0:
            raise ValueError("eta must be in (0, 1)")
        if self.obs_clip <= 0.0:
            raise ValueError("obs_clip must be > 0")


# ---------------------------------------------------------------------------
# Environment -- two definitions: real (gymnasium present) or sentinel.
# ---------------------------------------------------------------------------

if _GYM_AVAILABLE:

    class TradingEnv(gym.Env):  # type: ignore[misc]
        """A gymnasium-compatible single-instrument directional trading environment.

        The environment steps through a fixed, pre-supplied price series (plus any
        additional feature columns). The agent selects a discrete position at each
        step; the environment computes the log return, applies a transaction-cost
        penalty, and delivers the differential Sharpe ratio (DSR) update as the
        reward (Moody-Saffell 1998).

        Parameters
        ----------
        prices:
            1-D array of asset prices (at least ``window_size + 1`` elements).
            Log returns are computed as ``log(p[t+1] / p[t])``.
        features:
            2-D float array of shape ``(T, n_features)`` aligned to ``prices``
            (``len(features) == len(prices)``). Each row is the feature vector
            for that time step; the observation is a flattened window of
            ``window_size`` rows. If ``None``, a single feature equal to the
            one-step log return is auto-computed.
        config:
            Environment hyper-parameters; defaults to :class:`TradingEnvConfig`.

        Raises
        ------
        ValueError
            If ``prices`` has fewer than ``window_size + 1`` elements, or if
            ``features`` length does not match ``prices``.

        Notes
        -----
        * The episode terminates (``terminated = True``) when the agent has
          stepped through every price in the path.
        * ``truncated`` is always ``False``; there is no external time limit.
        * The environment is deterministic: the same seed + same action sequence
          always produces an identical reward trajectory.
        * ``render_modes`` is empty; :meth:`render` is a no-op.
        """

        metadata: dict[str, Any] = {"render_modes": []}

        def __init__(
            self,
            prices: np.ndarray,
            features: np.ndarray | None = None,
            config: TradingEnvConfig | None = None,
        ) -> None:
            super().__init__()
            self._config = config if config is not None else TradingEnvConfig()
            cfg = self._config

            prices_arr = np.asarray(prices, dtype=np.float64)
            if prices_arr.ndim != 1:
                raise ValueError("prices must be a 1-D array")
            min_len = cfg.window_size + 1
            if len(prices_arr) < min_len:
                raise ValueError(
                    f"prices must have at least window_size+1 = {min_len} elements; "
                    f"got {len(prices_arr)}"
                )

            if features is None:
                log_ret = np.log(prices_arr[1:] / prices_arr[:-1])
                feat = log_ret.reshape(-1, 1).astype(np.float32)
                # Prepend a zero row so features aligns with prices (same length).
                self._features: np.ndarray = np.vstack(
                    [np.zeros((1, 1), dtype=np.float32), feat]
                )
            else:
                feat_arr = np.asarray(features, dtype=np.float32)
                if feat_arr.ndim != 2:
                    raise ValueError("features must be a 2-D array")
                if len(feat_arr) != len(prices_arr):
                    raise ValueError(
                        f"features length ({len(feat_arr)}) must match "
                        f"prices length ({len(prices_arr)})"
                    )
                self._features = feat_arr

            self._prices: np.ndarray = prices_arr
            self._n_steps: int = len(prices_arr) - 1
            n_features = self._features.shape[1]
            obs_size = cfg.window_size * n_features

            self.observation_space: gym.spaces.Box = gym.spaces.Box(
                low=-cfg.obs_clip,
                high=cfg.obs_clip,
                shape=(obs_size,),
                dtype=np.float32,
            )
            self.action_space: gym.spaces.Discrete = gym.spaces.Discrete(3)

            # Episode state -- initialised fully in reset().
            self._current_step: int = 0
            self._position: float = 0.0
            self._dsr_A: float = 0.0
            self._dsr_B: float = 0.0

        @property
        def config(self) -> TradingEnvConfig:
            """The environment's hyper-parameters."""
            return self._config

        # --------------------------------------------------------------
        # gymnasium Env API
        # --------------------------------------------------------------

        def reset(
            self,
            *,
            seed: int | None = None,
            options: dict[str, Any] | None = None,
        ) -> tuple[np.ndarray, dict[str, Any]]:
            """Reset to the start of the price path.

            Parameters
            ----------
            seed:
                Optional integer seed. Forwarded to the gymnasium parent to
                initialise ``self.np_random``; does not affect the
                deterministic price/feature data.
            options:
                Ignored (no optional reset modes).

            Returns
            -------
            obs:
                Initial observation of shape ``(window_size * n_features,)``.
            info:
                Empty dict (gymnasium convention).
            """
            super().reset(seed=seed, options=options)

            self._current_step = 0
            self._position = 0.0
            self._dsr_A = 0.0
            self._dsr_B = 0.0

            return self._observe(), {}

        def step(
            self, action: int
        ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
            """Advance the environment by one time step.

            Parameters
            ----------
            action:
                Integer in ``{0, 1, 2}``: 0 = short, 1 = flat, 2 = long.

            Returns
            -------
            obs:
                Observation for the next step (or the terminal obs).
            reward:
                Differential Sharpe ratio update minus the transaction-cost
                penalty.
            terminated:
                ``True`` when the entire price path has been consumed.
            truncated:
                Always ``False``.
            info:
                Dict with ``position``, ``raw_return``, ``transaction_cost``,
                ``dsr_A`` and ``dsr_B`` for diagnostics.

            Raises
            ------
            RuntimeError
                If called after the episode has terminated without a reset.
            """
            if self._current_step >= self._n_steps:
                raise RuntimeError(
                    "step() called after episode has terminated; call reset() first"
                )

            cfg = self._config
            new_position = float(_ACTION_TO_POSITION[int(action)])

            # Transaction cost: proportional to the size of the position change.
            position_change = abs(new_position - self._position)
            transaction_cost = cfg.cost_pct * position_change

            # Log return for this step: the agent held the *old* position
            # through this bar.
            t = self._current_step
            log_ret = float(np.log(self._prices[t + 1] / self._prices[t]))
            raw_return = self._position * log_ret - transaction_cost

            # Update position *after* computing the return.
            self._position = new_position
            self._current_step += 1

            # Differential Sharpe ratio reward (Moody-Saffell 1998).
            reward = self._dsr_step(raw_return)

            terminated = self._current_step >= self._n_steps
            obs = self._observe()

            info: dict[str, Any] = {
                "position": new_position,
                "raw_return": raw_return,
                "transaction_cost": transaction_cost,
                "dsr_A": self._dsr_A,
                "dsr_B": self._dsr_B,
            }
            return obs, reward, terminated, False, info

        def render(self) -> None:
            """No-op render (render_modes is empty)."""

        def close(self) -> None:
            """No-op close."""

        # --------------------------------------------------------------
        # Internal helpers
        # --------------------------------------------------------------

        def _observe(self) -> np.ndarray:
            """Return the current observation: a clipped, flattened feature window."""
            cfg = self._config
            # Window ends at current_step (inclusive in features-index space);
            # pad with zeros at the start if history is shorter than window.
            end = self._current_step + 1
            start = end - cfg.window_size
            if start < 0:
                pad_rows = -start
                window = np.vstack(
                    [
                        np.zeros(
                            (pad_rows, self._features.shape[1]), dtype=np.float32
                        ),
                        self._features[:end],
                    ]
                )
            else:
                window = self._features[start:end]

            return np.clip(window.flatten(), -cfg.obs_clip, cfg.obs_clip).astype(
                np.float32
            )

        def _dsr_step(self, r: float) -> float:
            """Compute the DSR gradient reward for one return sample.

            The differential Sharpe ratio update (Moody-Saffell 1998) is the
            gradient of the instantaneous Sharpe ratio with respect to the
            current return.  Let::

                A_t = (1 - eta) * A_{t-1} + eta * r_t
                B_t = (1 - eta) * B_{t-1} + eta * r_t^2

            Then::

                delta_A = eta * (r_t - A_{t-1})
                delta_B = eta * (r_t^2 - B_{t-1})
                denom   = B_t - A_t^2             (variance estimate)

            When ``denom > eps``::

                DSR = (B_t * delta_A - 0.5 * A_t * delta_B) / denom^(3/2)

            When ``denom <= eps`` (near-zero variance, typically early in the
            episode), falls back to ``r_t`` so the agent gets a learning
            signal before the Sharpe denominator is meaningful.
            """
            eta = self._config.eta
            A_prev = self._dsr_A
            B_prev = self._dsr_B

            A_new = (1.0 - eta) * A_prev + eta * r
            B_new = (1.0 - eta) * B_prev + eta * r * r

            self._dsr_A = A_new
            self._dsr_B = B_new

            denom = B_new - A_new * A_new
            eps = 1e-8
            if denom <= eps:
                return r

            delta_A = eta * (r - A_prev)
            delta_B = eta * (r * r - B_prev)
            reward = (B_new * delta_A - 0.5 * A_new * delta_B) / (denom**1.5)
            return float(reward)

else:
    # gymnasium not installed: provide a sentinel class so the module remains
    # importable. Instantiation raises ImportError immediately.

    class TradingEnv:  # type: ignore[no-redef]
        """Sentinel: gymnasium is not installed.

        Instantiating this class raises :exc:`ImportError`. Install gymnasium
        with ``pip install gymnasium`` to use the real implementation.
        """

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            raise ImportError(
                "gymnasium is required for TradingEnv; install it with "
                "'pip install gymnasium'"
            )
