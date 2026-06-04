"""Reinforcement-learning trading agent wrapper (Phase 5.D.4).

A thin, reproducible wrapper around ``stable_baselines3`` that trains a PPO
(or DQN) policy on a :class:`~core_trading.signals.ml.rl.environment.TradingEnv`
and exposes a ``train`` / ``predict`` / ``save`` / ``load`` interface aligned
with the rest of Phase 5.D.

Design rationale
----------------
PPO is the default because it is on-policy (no replay buffer), stable across
a wide range of hyper-parameters, and works well with the relatively short
episodes produced by a fixed price path. DQN is available as an alternative
for environments where a larger replay buffer gives an advantage.

Reproducibility
---------------
Both the SB3 algorithm seed (``seed=``) and the training environment seed are
fixed at agent construction. SB3 also seeds the internal torch PRNG via its
``seed`` argument. Small net sizes (64 x 64) keep training fast and reduce the
variance of a single run.

Lazy import of ``stable_baselines3``
-------------------------------------
``stable_baselines3`` (and its ``torch`` dependency) is imported inside each
method that needs it, mirroring the ``scikit-learn`` pattern used elsewhere in
Phase 5.D.  This keeps the module importable in minimal environments and avoids
loading the full RL stack until an agent is actually trained or loaded.

On Windows, torch 2.12 CPU performs a DLL initialisation check
(``_load_dll_libraries``) that must complete before the DLL is first used.
The check succeeds reliably when torch is imported from a normal Python call
frame.  If torch is imported from inside pytest's assertion-rewriter hook
(during test collection), the DLL init may fail with an access violation.
The mandatory test command therefore uses ``import numpy`` as a module-level
pre-step; the smoke-train tests run after collection is complete, at which
point torch imports from inside a test function (normal call frame) and the
DLL check succeeds.

Mathematical references
-----------------------
* Schulman, J. et al. (2017). "Proximal Policy Optimization Algorithms."
  arXiv:1707.06347.
* Moody, J. and Saffell, M. (1998). "Optimizing Trading Systems using
  Automated Trading." Proc. AAAI-98 Spring Symposium on Intelligent Adaptive
  Agents for Financial Modeling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from core_trading.signals.ml.rl.environment import TradingEnv, TradingEnvConfig  # noqa: F401

__all__ = [
    "RLAgentConfig",
    "RLTradingAgent",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RLAgentConfig:
    """Hyper-parameters for :class:`RLTradingAgent`.

    Attributes
    ----------
    algorithm:
        Which SB3 algorithm to use: ``"PPO"`` (default, on-policy) or
        ``"DQN"`` (off-policy, requires discrete action space).
    policy:
        SB3 policy string, e.g. ``"MlpPolicy"`` (default). The policy is
        applied to the flattened observation vector.
    net_arch:
        Hidden-layer sizes for the policy network. Two layers of 64 units is
        sufficient for the small environments used in Phase 5.D.4.
    seed:
        Random seed for the SB3 algorithm and the training environment.
    n_steps:
        PPO-only: number of environment steps collected per update (must be
        a multiple of ``batch_size``). Ignored for DQN.
    batch_size:
        Mini-batch size for gradient updates.
    env_seed:
        Seed passed to ``env.reset()`` at the start of each training episode.
    """

    algorithm: Literal["PPO", "DQN"] = "PPO"
    policy: str = "MlpPolicy"
    net_arch: list[int] = field(default_factory=lambda: [64, 64])
    seed: int = 0
    n_steps: int = 128
    batch_size: int = 64
    env_seed: int = 0

    def __post_init__(self) -> None:
        if self.algorithm not in {"PPO", "DQN"}:
            raise ValueError("algorithm must be 'PPO' or 'DQN'")
        if not self.policy:
            raise ValueError("policy must be a non-empty string")
        if any(h < 1 for h in self.net_arch):
            raise ValueError("net_arch layer sizes must be >= 1")
        if self.n_steps < 1:
            raise ValueError("n_steps must be >= 1")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RLTradingAgent:
    """A thin wrapper around stable_baselines3 for RL-based directional trading.

    The agent trains a PPO (default) or DQN policy on a
    :class:`~core_trading.signals.ml.rl.environment.TradingEnv` and exposes a
    minimal ``train`` / ``predict`` / ``save`` / ``load`` interface.

    ``stable_baselines3`` is lazy-imported inside each method that needs it, so
    this class is importable in a minimal environment and only pulls the heavy
    RL stack when actually used.

    Parameters
    ----------
    env:
        The :class:`TradingEnv` instance to train on.
    config:
        Agent hyper-parameters; defaults to :class:`RLAgentConfig`.

    Raises
    ------
    ImportError
        If ``stable_baselines3`` is not installed when a method requiring it
        is first called.
    """

    def __init__(
        self,
        env: TradingEnv,
        config: RLAgentConfig | None = None,
    ) -> None:
        self._env = env
        self._config = config if config is not None else RLAgentConfig()
        self._model: Any | None = None

    @property
    def config(self) -> RLAgentConfig:
        """The agent's hyper-parameters."""
        return self._config

    @property
    def trained(self) -> bool:
        """Whether :meth:`train` has been called (or a model has been loaded)."""
        return self._model is not None

    def train(self, total_timesteps: int = 2000) -> RLTradingAgent:
        """Train the RL policy on the environment.

        Parameters
        ----------
        total_timesteps:
            Total environment steps for training (>= 1). Small values
            (500-2000) are sufficient for smoke-testing; convergence to a
            profitable policy on synthetic data requires far more steps and
            a meaningful feature set.

        Returns
        -------
        RLTradingAgent
            ``self``, trained.

        Raises
        ------
        ImportError
            If ``stable_baselines3`` is not installed.
        ValueError
            If ``total_timesteps < 1``.
        """
        if total_timesteps < 1:
            raise ValueError("total_timesteps must be >= 1")

        try:
            from stable_baselines3 import DQN, PPO
        except (ModuleNotFoundError, OSError) as exc:
            raise ImportError(
                "stable_baselines3 is required for RLTradingAgent.train(); "
                "install it with 'pip install stable-baselines3'"
            ) from exc

        cfg = self._config
        policy_kwargs: dict[str, Any] = {"net_arch": list(cfg.net_arch)}

        # Seed the environment before training.
        self._env.reset(seed=cfg.env_seed)

        if cfg.algorithm == "PPO":
            self._model = PPO(
                cfg.policy,
                self._env,
                n_steps=cfg.n_steps,
                batch_size=cfg.batch_size,
                policy_kwargs=policy_kwargs,
                verbose=0,
                seed=cfg.seed,
            )
        else:
            self._model = DQN(
                cfg.policy,
                self._env,
                batch_size=cfg.batch_size,
                policy_kwargs=policy_kwargs,
                learning_starts=0,
                verbose=0,
                seed=cfg.seed,
            )

        self._model.learn(total_timesteps=total_timesteps)
        return self

    def predict(
        self,
        obs: np.ndarray,
        *,
        deterministic: bool = True,
    ) -> int:
        """Predict the action for a single observation.

        Parameters
        ----------
        obs:
            Observation array of shape ``(obs_size,)`` matching the
            environment's observation space.
        deterministic:
            Whether to use the greedy (deterministic) policy. Defaults to
            ``True`` for consistent live predictions.

        Returns
        -------
        int
            Action index in ``{0, 1, 2}`` (short, flat, long).

        Raises
        ------
        RuntimeError
            If :meth:`train` has not been called (or no model has been
            loaded via :meth:`load`).
        """
        if self._model is None:
            raise RuntimeError(
                "RLTradingAgent is not trained; call train() or load() first"
            )
        obs_arr = np.asarray(obs, dtype=np.float32)
        action, _state = self._model.predict(obs_arr, deterministic=deterministic)
        return int(action)

    def save(self, path: str | Path) -> None:
        """Persist the trained policy to disk.

        Parameters
        ----------
        path:
            File path (a ``.zip`` extension is appended by SB3 if absent).

        Raises
        ------
        RuntimeError
            If the agent is not yet trained.
        """
        if self._model is None:
            raise RuntimeError(
                "RLTradingAgent is not trained; call train() before save()"
            )
        self._model.save(str(path))

    def load(self, path: str | Path) -> RLTradingAgent:
        """Load a previously saved policy from disk.

        Parameters
        ----------
        path:
            Path to the saved ``.zip`` file (the extension may be omitted;
            SB3 appends it automatically).

        Returns
        -------
        RLTradingAgent
            ``self``, with the loaded model attached.

        Raises
        ------
        ImportError
            If ``stable_baselines3`` is not installed.
        """
        try:
            from stable_baselines3 import DQN, PPO
        except (ModuleNotFoundError, OSError) as exc:
            raise ImportError(
                "stable_baselines3 is required for RLTradingAgent.load(); "
                "install it with 'pip install stable-baselines3'"
            ) from exc

        cfg = self._config
        if cfg.algorithm == "PPO":
            self._model = PPO.load(str(path), env=self._env)
        else:
            self._model = DQN.load(str(path), env=self._env)
        return self
