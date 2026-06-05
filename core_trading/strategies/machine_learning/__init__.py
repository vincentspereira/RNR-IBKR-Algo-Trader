"""Machine-learning strategies package (post-retirement stub).

The legacy ML god-class skeletons (ml_trading_strategies.py,
supervised_strategies.py, model_manager.py) and the root-level ml_strategies.py
were archived on 2026-06-05 to .archive/2026-06-05_strategy_retirement/ --
superseded by the Phase 5 ML signal library (weak-evidence variants dropped).

Retained here for later clean extraction (import directly):
- feature_engineering.py     -- feature pipeline logic
- reinforcement_learning.py  -- RL strategy logic
- clustering_strategies.py   -- working clustering impl (re-exported below)
- rl_strategy.py             -- working RL wrapper
"""

from .clustering_strategies import TradingState as ClusteringTradingState
from .clustering_strategies import create_clustering_strategy

__all__ = ["ClusteringTradingState", "create_clustering_strategy"]
