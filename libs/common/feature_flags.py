"""Feature Flag Management Module.

This module provides a simple, production-ready feature flag system
for the IBKR Algo-Trader project.
"""

import json
import os
from enum import Enum
from typing import Any


class FeatureStatus(str, Enum):
    """Feature status enumeration."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"


class FeatureFlag:
    """Individual feature flag with metadata."""
    
    def __init__(
        self,
        key: str,
        default_value: bool = False,
        status: FeatureStatus = FeatureStatus.DISABLED,
        description: str = "",
        depends_on: list | None = None
    ):
        """
        Initialize feature flag.
        
        Args:
            key: Unique identifier for the feature
            default_value: Default boolean value
            status: Feature status
            description: Human-readable description
            depends_on: List of feature keys this feature depends on
        """
        self.key = key
        self.default_value = default_value
        self.status = status
        self.description = description
        self.depends_on = depends_on or []
        self._value: bool | None = None
    
    def is_enabled(self, flags: dict[str, bool] | None = None) -> bool:
        """
        Check if feature is enabled.
        
        Args:
            flags: Current flag values (uses environment if None)
            
        Returns:
            True if feature is enabled
        """
        if self.status == FeatureStatus.DISABLED:
            return False
        
        if self.status == FeatureStatus.ENABLED:
            return True
        
        # Use provided flags or check environment variables
        value = flags.get(self.key) if flags else self._get_env_value()
        
        # Check dependencies
        if self.depends_on:
            for dep_key in self.depends_on:
                _dep_value = flags.get(dep_key) if flags else self._get_env_value(dep_key)
                if not _dep_value:
                    return False
        
        # Use explicit value, then default
        if value is not None:
            return value
        
        return self.default_value
    
    def _get_env_value(self, key: str | None = None) -> bool | None:
        """
        Get value from environment variable.
        
        Args:
            key: Feature key (uses self.key if None)
            
        Returns:
            Boolean value from environment
        """
        _key = key or self.key
        env_var_name = f"FEATURE_{_key.upper()}"
        env_value = os.getenv(env_var_name)
        
        if env_value is not None:
            return env_value.lower() in ("true", "1", "yes", "on")
        
        return None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert flag to dictionary."""
        return {
            "key": self.key,
            "status": self.status.value,
            "default_value": self.default_value,
            "description": self.description,
            "depends_on": self.depends_on,
            "current_value": self.is_enabled()
        }


class FeatureFlags:
    """Centralized feature flag manager."""
    
    # Define all system features
    FEATURE_DEFINITIONS = {
        # Trading Features
        "live_trading": FeatureFlag(
            key="live_trading",
            default_value=False,
            status=FeatureStatus.DISABLED,
            description="Enable live trading (production orders)",
            depends_on=["risk_management", "order_management"]
        ),
        "paper_trading": FeatureFlag(
            key="paper_trading",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable paper trading (simulated orders)"
        ),
        "options_trading": FeatureFlag(
            key="options_trading",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable options trading and analytics",
            depends_on=["volatility_pricing"]
        ),
        
        # Analysis Features
        "technical_analysis": FeatureFlag(
            key="technical_analysis",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable technical analysis indicators"
        ),
        "fundamental_analysis": FeatureFlag(
            key="fundamental_analysis",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable fundamental analysis calculations"
        ),
        "ml_strategies": FeatureFlag(
            key="ml_strategies",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable ML-based trading strategies",
            depends_on=["technical_analysis"]
        ),
        
        # AI Features
        "ai_assistant": FeatureFlag(
            key="ai_assistant",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable AI assistant for natural language queries"
        ),
        "rag_search": FeatureFlag(
            key="rag_search",
            default_value=True,
            status=FeatureStatus.ENABLED,
            description="Enable RAG-based search in AI assistant",
            depends_on=["qdrant_vector_db"]
        ),
        
        # Experimental Features
        "sentiment_analysis": FeatureFlag(
            key="sentiment_analysis",
            default_value=False,
            status=FeatureStatus.EXPERIMENTAL,
            description="Enable sentiment analysis trading signals"
        ),
        "social_trading": FeatureFlag(
            key="social_trading",
            default_value=False,
            status=FeatureStatus.EXPERIMENTAL,
            description="Enable social/copy trading features"
        ),
    }
    
    _current_flags: dict[str, bool] | None = None
    
    @classmethod
    def is_enabled(cls, feature_key: str) -> bool:
        """
        Check if a feature is enabled.
        
        Args:
            feature_key: Unique feature identifier
            
        Returns:
            True if feature is enabled
        """
        if feature_key not in cls.FEATURE_DEFINITIONS:
            raise ValueError(f"Unknown feature flag: {feature_key}")
        
        flag = cls.FEATURE_DEFINITIONS[feature_key]
        return flag.is_enabled(cls._current_flags)
    
    @classmethod
    def get_all_flags(cls) -> dict[str, Any]:
        """
        Get all feature flags with their status.
        
        Returns:
            Dictionary of all flags
        """
        result = {}
        for key, flag_def in cls.FEATURE_DEFINITIONS.items():
            result[key] = flag_def.to_dict()
        return result
    
    @classmethod
    def load_from_file(cls, file_path: str) -> None:
        """
        Load feature flags from configuration file.
        
        Args:
            file_path: Path to JSON configuration file
        """
        try:
            with open(file_path) as f:
                cls._current_flags = json.load(f)
        except FileNotFoundError:
            cls._current_flags = {}
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid feature flag file: {e}") from e
    
    @classmethod
    def load_from_env(cls) -> None:
        """
        Load feature flags from environment variables.
        Environment variables should be prefixed with FEATURE_
        """
        cls._current_flags = None  # Let flags read from env
    
    @classmethod
    def export_to_file(cls, file_path: str) -> None:
        """
        Export current flag values to JSON file.
        
        Args:
            file_path: Output file path
        """
        flags = cls.get_all_flags()
        with open(file_path, 'w') as f:
            json.dump(flags, f, indent=2)


# Convenience functions
def is_enabled(feature_key: str) -> bool:
    """
    Check if a feature is enabled.
    
    Args:
        feature_key: Feature identifier
        
    Returns:
        True if feature is enabled
    """
    return FeatureFlags.is_enabled(feature_key)


def get_flags() -> dict[str, Any]:
    """Get all feature flags."""
    return FeatureFlags.get_all_flags()


# Usage Examples
if __name__ == "__main__":
    # Load from environment by default
    FeatureFlags.load_from_env()
    
    # Check features
    print(f"Paper Trading Enabled: {FeatureFlags.is_enabled('paper_trading')}")
    print(f"Live Trading Enabled: {FeatureFlags.is_enabled('live_trading')}")
    print(f"Options Trading Enabled: {FeatureFlags.is_enabled('options_trading')}")
    print(f"AI Assistant Enabled: {FeatureFlags.is_enabled('ai_assistant')}")
    print(f"ML Strategies Enabled: {FeatureFlags.is_enabled('ml_strategies')}")
    
    # Export all flags
    FeatureFlags.export_to_file("feature_flags.json")
    print("\nFeature flags exported to feature_flags.json")
