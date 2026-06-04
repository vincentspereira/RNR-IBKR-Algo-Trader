"""Reinforcement-learning signal family (Phase 5.D.4).

This subpackage delivers the RL-based directional trading infrastructure for
the 5.D machine-learning toolkit. It replaces the 77%-commented legacy shell
``machine_learning/reinforcement_learning.py``.

The architecture is a thin wrapper around ``stable_baselines3`` with a
gymnasium-compatible trading environment whose reward signal is the
**differential Sharpe ratio** (Moody & Saffell, 1998) -- a risk-adjusted,
online reward that penalises variance and discourages churn via a proportional
transaction-cost penalty.

Public API
----------
:class:`TradingEnvConfig`
    Hyper-parameters for the gymnasium trading environment: window size,
    transaction-cost rate, DSR smoothing factor, and observation clip bound.
:class:`TradingEnv`
    A gymnasium ``Env`` implementing discrete (short / flat / long) trading
    on a fixed price path with a DSR reward. Validated by
    :func:`gymnasium.utils.env_checker.check_env`.
:class:`RLAgentConfig`
    Hyper-parameters for the RL agent: algorithm (PPO / DQN), policy net
    architecture, seeds, and SB3 update parameters.
:class:`RLTradingAgent`
    A reproducible ``stable_baselines3`` wrapper with ``train``, ``predict``,
    ``save``, and ``load``.

Usage sketch
------------
::

    import numpy as np
    from core_trading.signals.ml.rl import TradingEnv, RLTradingAgent

    prices = np.cumprod(1 + np.random.normal(0, 0.01, 500)) * 100
    env = TradingEnv(prices=prices)
    agent = RLTradingAgent(env)
    agent.train(total_timesteps=5000)

    obs, _ = env.reset()
    action = agent.predict(obs)   # 0=short, 1=flat, 2=long

Mathematical references
-----------------------
* Moody, J. and Saffell, M. (1998). "Optimizing Trading Systems using
  Automated Trading." Proc. AAAI-98 Spring Symposium on Intelligent Adaptive
  Agents for Financial Modeling.
* Schulman, J. et al. (2017). "Proximal Policy Optimization Algorithms."
  arXiv:1707.06347.
"""
from __future__ import annotations

from core_trading.signals.ml.rl.agent import RLAgentConfig, RLTradingAgent
from core_trading.signals.ml.rl.environment import TradingEnv, TradingEnvConfig

__all__ = [
    "TradingEnvConfig",
    "TradingEnv",
    "RLAgentConfig",
    "RLTradingAgent",
]
