"""Configuration management using Pydantic Settings."""
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    """Database configuration."""
    
    # PostgreSQL
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_user: str = Field(default="trading_user", description="PostgreSQL user")
    postgres_password: str = Field(..., description="PostgreSQL password")
    postgres_db: str = Field(default="trading", description="PostgreSQL database")
    postgres_pool_size: int = Field(default=20, description="Connection pool size")
    
    # ClickHouse
    clickhouse_host: str = Field(default="localhost", description="ClickHouse host")
    clickhouse_port: int = Field(default=8123, description="ClickHouse HTTP port")
    clickhouse_password: str = Field(..., description="ClickHouse password")
    clickhouse_db: str = Field(default="trading", description="ClickHouse database")
    
    # Neo4j
    neo4j_uri: str = Field(default="bolt://localhost:7687", description="Neo4j URI")
    neo4j_password: str = Field(..., description="Neo4j password")
    
    # Redis
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: str = Field(..., description="Redis password")
    redis_pool_size: int = Field(default=50, description="Redis pool size")
    
    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333", description="Qdrant URL")
    qdrant_api_key: Optional[str] = Field(None, description="Qdrant API key")
    
    @property
    def postgres_url(self) -> str:
        """Get PostgreSQL connection URL."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def postgres_async_url(self) -> str:
        """Get PostgreSQL async connection URL."""
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


class KafkaConfig(BaseSettings):
    """Kafka configuration."""
    
    bootstrap_servers: str = Field(default="localhost:9092", description="Kafka bootstrap servers")
    schema_registry_url: str = Field(default="http://localhost:8081", description="Schema Registry URL")
    consumer_group_id: str = Field(default="trading-system-consumers", description="Consumer group ID")
    
    @property
    def bootstrap_servers_list(self) -> List[str]:
        """Get bootstrap servers as list."""
        return self.bootstrap_servers.split(",")


class SecurityConfig(BaseSettings):
    """Security configuration."""
    
    jwt_secret: str = Field(..., description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_access_token_expiry: str = Field(default="15m", description="Access token expiry")
    jwt_refresh_token_expiry: str = Field(default="7d", description="Refresh token expiry")
    
    # Keycloak
    keycloak_server_url: str = Field(default="http://localhost:8080", description="Keycloak server URL")
    keycloak_realm: str = Field(default="trading", description="Keycloak realm")
    keycloak_client_id: str = Field(default="trading-system", description="Keycloak client ID")
    keycloak_client_secret: Optional[str] = Field(None, description="Keycloak client secret")


class APIConfig(BaseSettings):
    """External API configuration."""
    
    alpha_vantage_api_key: str = Field(..., description="Alpha Vantage API key")
    financial_modeling_prep_api_key: Optional[str] = Field(None, description="Financial Modeling Prep API key")
    
    # AI/ML APIs
    openai_api_key: Optional[str] = Field(None, description="OpenAI API key")
    groq_api_key: Optional[str] = Field(None, description="Groq API key")
    deepseek_api_key: Optional[str] = Field(None, description="DeepSeek API key")
    gemini_api_key: Optional[str] = Field(None, description="Gemini API key")
    
    # Local models
    ollama_url: str = Field(default="http://localhost:11434", description="Ollama URL")
    default_embedding_model: str = Field(default="snowflake-arctic-embed2:568m", description="Default embedding model")


class FeatureFlags(BaseSettings):
    """Feature flags."""
    
    feature_live_trading_enabled: bool = Field(default=False, description="Enable live trading")
    feature_options_trading_enabled: bool = Field(default=True, description="Enable options trading")
    feature_ml_strategies_enabled: bool = Field(default=True, description="Enable ML strategies")
    feature_fundamental_analysis_enabled: bool = Field(default=True, description="Enable fundamental analysis")
    feature_ai_assistant_enabled: bool = Field(default=True, description="Enable AI assistant")


class AppConfig(BaseSettings):
    """Main application configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = Field(default="Trading System", description="Application name")
    app_version: str = Field(default="1.0.0", description="Application version")
    environment: str = Field(default="development", description="Environment")
    debug: bool = Field(default=True, description="Debug mode")
    
    # Logging
    log_level: str = Field(default="INFO", description="Log level")
    log_format: str = Field(default="json", description="Log format")
    
    # Service
    service_name: Optional[str] = Field(None, description="Service name")
    service_port: int = Field(default=8000, description="Service port")
    
    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    features: FeatureFlags = Field(default_factory=FeatureFlags)


# Global config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Get application configuration singleton.
    
    Returns:
        Application configuration
    """
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reload_config() -> AppConfig:
    """
    Reload configuration from environment.
    
    Returns:
        Reloaded configuration
    """
    global _config
    _config = AppConfig()
    return _config
