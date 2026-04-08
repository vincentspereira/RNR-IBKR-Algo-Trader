"""Clustering Strategies Module for Algorithmic Trading System.

This module implements unsupervised machine learning strategies for market regime
detection, anomaly detection, and pattern recognition. It follows the 5-Pillar
Architecture using pure numpy implementations so it works without sklearn installed.

Key components:
- RegimeType enum: market regime classification
- ClusteringMethod enum: supported clustering algorithms
- AnomalyMethod enum: anomaly detection algorithm types
- RegimeState: current market regime snapshot
- ClusteringConfig: strategy configuration
- MarketRegimeDetector: regime detection via feature clustering
- AnomalyDetectionStrategy: statistical anomaly detection
- ClusteringStrategy: combines regime + anomaly for signal generation
"""

import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RegimeType(Enum):
    """Market regime types."""

    BULL_MARKET = "bull_market"
    BEAR_MARKET = "bear_market"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    CRISIS = "crisis"
    RECOVERY = "recovery"
    UNKNOWN = "unknown"


class ClusteringMethod(Enum):
    """Clustering algorithm types."""

    KMEANS = "kmeans"
    GAUSSIAN_MIXTURE = "gaussian_mixture"
    DBSCAN = "dbscan"
    HIERARCHICAL = "hierarchical"
    SPECTRAL = "spectral"


class AnomalyMethod(Enum):
    """Anomaly detection methods."""

    ISOLATION_FOREST = "isolation_forest"
    ONE_CLASS_SVM = "one_class_svm"
    ELLIPTIC_ENVELOPE = "elliptic_envelope"
    LOCAL_OUTLIER_FACTOR = "local_outlier_factor"
    STATISTICAL = "statistical"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RegimeState:
    """Current market regime state."""

    regime_type: RegimeType = RegimeType.UNKNOWN
    confidence: float = 0.0
    duration: int = 0
    stability: float = 0.0
    transition_probability: Dict[RegimeType, float] = field(default_factory=dict)
    features: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ClusteringConfig:
    """Configuration for clustering strategies."""

    # Clustering parameters
    n_clusters: int = 4
    clustering_method: ClusteringMethod = ClusteringMethod.KMEANS
    lookback_period: int = 252
    min_regime_duration: int = 5

    # Feature selection
    use_technical_features: bool = True
    use_volatility_features: bool = True
    use_volume_features: bool = True
    use_macro_features: bool = False

    # Preprocessing
    scaler_type: str = "robust"
    use_pca: bool = True
    pca_components: float = 0.95

    # Regime detection
    regime_smoothing: int = 3
    confidence_threshold: float = 0.6

    # Anomaly detection
    anomaly_method: AnomalyMethod = AnomalyMethod.STATISTICAL
    anomaly_threshold: float = 0.1

    # Performance
    refit_frequency: int = 21
    parallel_jobs: int = -1


# ---------------------------------------------------------------------------
# Helper: minimal KMeans in pure numpy
# ---------------------------------------------------------------------------


def _simple_kmeans(
    data: np.ndarray, n_clusters: int, max_iter: int = 100, seed: int = 42
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit a simple KMeans clusterer using pure numpy.

    Args:
        data: 2-D array of shape (n_samples, n_features).
        n_clusters: Number of clusters.
        max_iter: Maximum iterations.
        seed: Random seed for centroid initialisation.

    Returns:
        Tuple of (labels, centroids).
    """
    rng = np.random.default_rng(seed)
    n_samples = data.shape[0]

    if n_samples <= n_clusters:
        labels = np.arange(n_samples) % n_clusters
        centroids = np.zeros((n_clusters, data.shape[1]))
        for k in range(n_clusters):
            mask = labels == k
            if mask.any():
                centroids[k] = data[mask].mean(axis=0)
        return labels, centroids

    # Random initialisation
    indices = rng.choice(n_samples, size=n_clusters, replace=False)
    centroids = data[indices].copy()

    labels = np.zeros(n_samples, dtype=int)
    for _ in range(max_iter):
        # Assign each point to nearest centroid
        distances = np.array(
            [np.sum((data - c) ** 2, axis=1) for c in centroids]
        )  # (n_clusters, n_samples)
        new_labels = np.argmin(distances, axis=0)

        if np.array_equal(new_labels, labels):
            break
        labels = new_labels

        # Update centroids
        for k in range(n_clusters):
            mask = labels == k
            if mask.any():
                centroids[k] = data[mask].mean(axis=0)

    return labels, centroids


def _robust_scale(data: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scale data using median and IQR (robust scaling).

    Args:
        data: 2-D array of shape (n_samples, n_features).

    Returns:
        Tuple of (scaled_data, center, scale).
    """
    center = np.median(data, axis=0)
    q75 = np.percentile(data, 75, axis=0)
    q25 = np.percentile(data, 25, axis=0)
    scale = (q75 - q25)
    scale[scale == 0] = 1.0
    scaled = (data - center) / scale
    return scaled, center, scale


# ---------------------------------------------------------------------------
# MarketRegimeDetector
# ---------------------------------------------------------------------------


class MarketRegimeDetector:
    """Market regime detection using clustering of extracted features."""

    def __init__(self, config: Optional[ClusteringConfig] = None):
        self.config = config or ClusteringConfig()
        self.centroids: Optional[np.ndarray] = None
        self.scaler_center: Optional[np.ndarray] = None
        self.scaler_scale: Optional[np.ndarray] = None
        self.regime_history: List[RegimeState] = []
        self.last_refit: Optional[datetime] = None

        # Map cluster indices to regime types (will be determined during fit)
        self.regime_mapping: Dict[int, RegimeType] = {}

    # -- feature extraction --------------------------------------------------

    def extract_regime_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract features for regime detection.

        Returns a DataFrame of engineered features indexed like *data*.
        """
        features = pd.DataFrame(index=data.index)
        close = data["close"]

        # Price-based features
        features["returns"] = close.pct_change()
        features["log_returns"] = np.log(close / close.shift(1))
        features["price_momentum_5"] = close.pct_change(5)
        features["price_momentum_20"] = close.pct_change(20)

        # Volatility features
        features["realized_vol_5"] = features["returns"].rolling(5).std()
        features["realized_vol_20"] = features["returns"].rolling(20).std()
        vol_20 = features["realized_vol_20"].replace(0, np.nan)
        features["vol_ratio"] = features["realized_vol_5"] / vol_20

        # Trend features
        features["sma_5"] = close.rolling(5).mean()
        features["sma_20"] = close.rolling(20).mean()
        sma_20 = features["sma_20"].replace(0, np.nan)
        features["trend_strength"] = (close - features["sma_20"]) / sma_20

        if "high" in data.columns and "low" in data.columns:
            low_20 = data["low"].rolling(20).min()
            high_20 = data["high"].rolling(20).max()
            range_20 = (high_20 - low_20).replace(0, np.nan)
            features["price_position"] = (close - low_20) / range_20
            features["hl_ratio"] = (data["high"] - data["low"]) / close.replace(0, np.nan)

        if "volume" in data.columns:
            vol_sma = data["volume"].rolling(20).mean().replace(0, np.nan)
            features["volume_ratio"] = data["volume"] / vol_sma

        # Clean
        features = features.replace([np.inf, -np.inf], np.nan)
        features = features.ffill().fillna(0)
        return features

    # -- fit / predict -------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> "MarketRegimeDetector":
        """Fit the regime detection model on historical data."""
        features = self.extract_regime_features(data)
        feature_matrix = features.dropna()

        if len(feature_matrix) < self.config.n_clusters:
            logger.warning("Insufficient data for clustering: %d rows", len(feature_matrix))
            return self

        raw = feature_matrix.values

        # Scale
        scaled, self.scaler_center, self.scaler_scale = _robust_scale(raw)

        # Cluster
        labels, self.centroids = _simple_kmeans(
            scaled, self.config.n_clusters, max_iter=50, seed=42
        )

        # Build regime mapping by inspecting centroid characteristics.
        # We sort clusters by mean return -> bullish first, bearish last.
        centroid_means = []
        for k in range(self.config.n_clusters):
            mask = labels == k
            if mask.any():
                mean_ret = scaled[mask, 0].mean()  # column 0 = returns
            else:
                mean_ret = 0.0
            centroid_means.append(mean_ret)

        sorted_indices = np.argsort(centroid_means)[::-1]  # highest return first
        regime_order = [
            RegimeType.BULL_MARKET,
            RegimeType.TRENDING,
            RegimeType.SIDEWAYS,
            RegimeType.BEAR_MARKET,
            RegimeType.HIGH_VOLATILITY,
            RegimeType.LOW_VOLATILITY,
            RegimeType.MEAN_REVERTING,
            RegimeType.CRISIS,
            RegimeType.RECOVERY,
        ]
        for rank, idx in enumerate(sorted_indices):
            self.regime_mapping[int(idx)] = regime_order[rank % len(regime_order)]

        self.last_refit = datetime.now()
        logger.info("Market regime detector fitted with %d clusters", self.config.n_clusters)
        return self

    def predict_regime(self, data: pd.DataFrame) -> RegimeState:
        """Predict current market regime from data."""
        if self.centroids is None:
            return RegimeState(regime_type=RegimeType.UNKNOWN, confidence=0.0)

        features = self.extract_regime_features(data)
        latest = features.iloc[-1:].values

        if np.any(np.isnan(latest)):
            return RegimeState(regime_type=RegimeType.UNKNOWN, confidence=0.0)

        # Scale using stored parameters
        scaled = (latest - self.scaler_center) / self.scaler_scale

        # Assign to nearest centroid
        distances = np.array([np.sum((scaled[0] - c) ** 2) for c in self.centroids])
        cluster_id = int(np.argmin(distances))
        min_dist = distances[cluster_id]
        max_dist = distances.max()

        # Confidence from distance ratio
        confidence = 1.0 - (min_dist / max_dist) if max_dist > 0 else 0.5
        confidence = max(0.0, min(1.0, confidence))

        regime_type = self.regime_mapping.get(cluster_id, RegimeType.UNKNOWN)

        state = RegimeState(
            regime_type=regime_type,
            confidence=confidence,
            duration=self._calculate_regime_duration(regime_type),
            stability=self._calculate_regime_stability(regime_type),
        )
        self.regime_history.append(state)
        if len(self.regime_history) > 1000:
            self.regime_history = self.regime_history[-1000:]
        return state

    # -- helpers -------------------------------------------------------------

    def _calculate_regime_duration(self, current: RegimeType) -> int:
        """Count consecutive periods in the current regime."""
        duration = 0
        for state in reversed(self.regime_history):
            if state.regime_type == current:
                duration += 1
            else:
                break
        return duration

    def _calculate_regime_stability(self, current: RegimeType) -> float:
        """Fraction of recent history spent in the current regime."""
        if len(self.regime_history) < 10:
            return 0.5
        recent = [s.regime_type for s in self.regime_history[-20:]]
        return recent.count(current) / len(recent)


# ---------------------------------------------------------------------------
# AnomalyDetectionStrategy
# ---------------------------------------------------------------------------


class AnomalyDetectionStrategy:
    """Statistical anomaly detection for market conditions.

    Uses z-score based detection on feature vectors so it does not require
    sklearn or other ML libraries.
    """

    def __init__(self, config: Optional[ClusteringConfig] = None):
        self.config = config or ClusteringConfig()
        self.feature_means: Optional[np.ndarray] = None
        self.feature_stds: Optional[np.ndarray] = None
        self.anomaly_history: List[Tuple[datetime, float, bool]] = []

    def fit(self, data: pd.DataFrame) -> "AnomalyDetectionStrategy":
        """Fit anomaly detection model on historical data."""
        features = self._extract_anomaly_features(data)
        cleaned = features.replace([np.inf, -np.inf], np.nan).dropna()
        if len(cleaned) == 0:
            return self

        values = cleaned.values
        self.feature_means = np.mean(values, axis=0)
        self.feature_stds = np.std(values, axis=0)
        self.feature_stds[self.feature_stds == 0] = 1.0
        return self

    def detect_anomalies(self, data: pd.DataFrame) -> Tuple[bool, float]:
        """Detect if current market conditions are anomalous.

        Returns:
            Tuple of (is_anomaly, anomaly_score in [0, 1]).
        """
        if self.feature_means is None:
            return False, 0.5

        features = self._extract_anomaly_features(data)
        latest = features.iloc[-1:].replace([np.inf, -np.inf], np.nan).fillna(0).values

        if latest.shape[1] != len(self.feature_means):
            return False, 0.5

        # Z-score distance
        z_scores = (latest[0] - self.feature_means) / self.feature_stds
        score = float(np.mean(np.abs(z_scores)))

        # Normalise: score > 2 is typically anomalous
        is_anomaly = score > 2.0
        normalised = min(score / 4.0, 1.0)

        self.anomaly_history.append((datetime.now(), normalised, is_anomaly))
        if len(self.anomaly_history) > 1000:
            self.anomaly_history = self.anomaly_history[-1000:]

        return is_anomaly, normalised

    def _extract_anomaly_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract features used for anomaly scoring."""
        features = pd.DataFrame(index=data.index)
        close = data["close"]

        features["returns"] = close.pct_change().fillna(0)
        features["volatility"] = features["returns"].rolling(20).std().fillna(0)
        features["price_change_5d"] = close.pct_change(5).fillna(0)

        if "volume" in data.columns:
            vol_mean = data["volume"].rolling(20).mean().replace(0, np.nan)
            features["volume_spike"] = (data["volume"] / vol_mean).fillna(1.0)

        if "high" in data.columns and "low" in data.columns:
            features["range"] = ((data["high"] - data["low"]) / close.replace(0, np.nan)).fillna(0)

        features = features.replace([np.inf, -np.inf], np.nan).fillna(0)
        return features


# ---------------------------------------------------------------------------
# ClusteringStrategy  (main entry point)
# ---------------------------------------------------------------------------


class ClusteringStrategy:
    """Combines regime detection and anomaly detection to generate signals.

    Usage::

        config = ClusteringConfig(n_clusters=4)
        strategy = ClusteringStrategy(config)
        strategy.fit(training_data)
        signals = strategy.generate_signals(new_data)
    """

    def __init__(self, config: Optional[ClusteringConfig] = None):
        self.config = config or ClusteringConfig()
        self.regime_detector = MarketRegimeDetector(self.config)
        self.anomaly_detector = AnomalyDetectionStrategy(self.config)
        self.current_regime: Optional[RegimeState] = None
        self.is_anomalous: bool = False
        self.anomaly_score: float = 0.0
        self._fitted: bool = False

        # Strategy parameters by regime
        self.regime_parameters: Dict[RegimeType, Dict[str, float]] = {
            RegimeType.BULL_MARKET: {
                "position_size": 1.0,
                "stop_loss": 0.05,
                "take_profit": 0.15,
            },
            RegimeType.BEAR_MARKET: {
                "position_size": 0.5,
                "stop_loss": 0.03,
                "take_profit": 0.08,
            },
            RegimeType.SIDEWAYS: {
                "position_size": 0.7,
                "stop_loss": 0.02,
                "take_profit": 0.05,
            },
            RegimeType.HIGH_VOLATILITY: {
                "position_size": 0.3,
                "stop_loss": 0.02,
                "take_profit": 0.10,
            },
            RegimeType.LOW_VOLATILITY: {
                "position_size": 1.2,
                "stop_loss": 0.03,
                "take_profit": 0.08,
            },
        }

    # -- fit / update --------------------------------------------------------

    def fit(self, data: pd.DataFrame) -> "ClusteringStrategy":
        """Fit both regime detector and anomaly detector."""
        self.regime_detector.fit(data)
        self.anomaly_detector.fit(data)
        self._fitted = True
        return self

    def update(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Update regime and anomaly detection from new data."""
        self.current_regime = self.regime_detector.predict_regime(data)
        self.is_anomalous, self.anomaly_score = self.anomaly_detector.detect_anomalies(data)

        regime_type = self.current_regime.regime_type if self.current_regime else RegimeType.SIDEWAYS
        params = self.regime_parameters.get(regime_type, self.regime_parameters[RegimeType.SIDEWAYS]).copy()

        if self.is_anomalous:
            params["position_size"] *= 0.5
            params["stop_loss"] *= 0.7

        return {
            "regime": self.current_regime,
            "is_anomalous": self.is_anomalous,
            "anomaly_score": self.anomaly_score,
            "parameters": params,
            "confidence": self.current_regime.confidence if self.current_regime else 0.0,
        }

    # -- signal generation ---------------------------------------------------

    def generate_signals(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """Generate trading signals based on regime and anomaly state.

        Each signal is a dict with keys: direction, confidence, strength,
        regime, is_anomalous, anomaly_score, parameters.

        Args:
            data: OHLCV DataFrame with at least ``lookback_period`` rows.

        Returns:
            List of signal dictionaries. Empty list if data is insufficient
            or the model has not been fitted.
        """
        if not self._fitted:
            # Auto-fit if data is sufficient
            min_rows = max(self.config.lookback_period, 50)
            if len(data) < min_rows:
                return []
            self.fit(data)

        if len(data) < self.config.min_regime_duration + 1:
            return []

        result = self.update(data)
        regime = result["regime"]
        confidence = result["confidence"]

        if regime is None or regime.regime_type == RegimeType.UNKNOWN:
            return []

        # Determine signal direction from regime
        bullish_regimes = {
            RegimeType.BULL_MARKET,
            RegimeType.TRENDING,
            RegimeType.RECOVERY,
            RegimeType.LOW_VOLATILITY,
        }
        bearish_regimes = {
            RegimeType.BEAR_MARKET,
            RegimeType.CRISIS,
            RegimeType.HIGH_VOLATILITY,
        }

        if regime.regime_type in bullish_regimes:
            direction = "buy"
        elif regime.regime_type in bearish_regimes:
            direction = "sell"
        else:
            direction = "hold"

        # Reduce confidence during anomalies
        effective_confidence = confidence * (0.5 if result["is_anomalous"] else 1.0)

        # Signal strength is based on confidence and regime stability
        strength = min(effective_confidence * regime.stability, 1.0)

        signal = {
            "direction": direction,
            "confidence": effective_confidence,
            "strength": strength,
            "regime": regime.regime_type.value,
            "is_anomalous": result["is_anomalous"],
            "anomaly_score": result["anomaly_score"],
            "parameters": result["parameters"],
        }
        return [signal]

    # -- query helpers -------------------------------------------------------

    def should_refit(self) -> bool:
        """Check if model should be refitted."""
        if self.regime_detector.last_refit is None:
            return True
        days_since = (datetime.now() - self.regime_detector.last_refit).days
        return days_since >= self.config.refit_frequency

    def get_regime_summary(self) -> Dict[str, Any]:
        """Get summary of recent regime history."""
        if not self.regime_detector.regime_history:
            return {}

        recent = self.regime_detector.regime_history[-50:]
        counts: Dict[RegimeType, int] = {}
        for state in recent:
            counts[state.regime_type] = counts.get(state.regime_type, 0) + 1

        total = len(recent)
        distribution = {rt.value: cnt / total for rt, cnt in counts.items()}
        avg_conf = float(np.mean([s.confidence for s in recent]))

        return {
            "current_regime": self.current_regime.regime_type.value if self.current_regime else "unknown",
            "regime_distribution": distribution,
            "average_confidence": avg_conf,
            "regime_changes": len({s.regime_type for s in recent}),
        }

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Return current indicator/feature values for display.

        Returns empty dict when data is insufficient.
        """
        if len(data) < 10:
            return {}

        features = self.regime_detector.extract_regime_features(data)
        latest = features.iloc[-1]

        regime_state = None
        if self._fitted:
            regime_state = self.regime_detector.predict_regime(data)

        values = {
            "returns": float(latest.get("returns", 0)),
            "vol_5": float(latest.get("realized_vol_5", 0)),
            "vol_20": float(latest.get("realized_vol_20", 0)),
            "trend_strength": float(latest.get("trend_strength", 0)),
        }
        if regime_state is not None:
            values["regime"] = regime_state.regime_type.value
            values["regime_confidence"] = regime_state.confidence

        return values


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_clustering_strategy(
    config: Optional[ClusteringConfig] = None,
) -> ClusteringStrategy:
    """Factory function to create a clustering strategy."""
    return ClusteringStrategy(config)


# Alias so that __init__.py can do ``from .clustering_strategies import TradingState``
TradingState = RegimeState
