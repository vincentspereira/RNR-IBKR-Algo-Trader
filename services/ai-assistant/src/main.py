"""AI-Powered Trading Assistant Service.

Provides intelligent trading analysis using LLMs and vector store:
- Trading signal analysis with LLM reasoning
- AI-assisted risk assessment
- Natural language query answering about portfolio and markets
- Knowledge management via Qdrant vector store
- Event-driven integration with the trading system
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, List, Optional

logger = logging.getLogger("AIAssistant")

# ---------------------------------------------------------------------------
# Conditional imports with graceful fallbacks
# ---------------------------------------------------------------------------

try:
    from libs.common.config import get_config
    from libs.common.logging import get_logger as get_structlog
    from libs.common.monitoring.health import HealthChecker, HealthStatus, HealthCheckResult

    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False

try:
    from libs.database.qdrant.client import QdrantClient, get_qdrant_client

    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False
    QdrantClient = None

try:
    from libs.messaging.producers.kafka_producer import KafkaProducer, get_kafka_producer

    HAS_KAFKA = True
except ImportError:
    HAS_KAFKA = False
    KafkaProducer = None

try:
    from openai import AsyncOpenAI

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    AsyncOpenAI = None

try:
    from sentence_transformers import SentenceTransformer

    HAS_EMBEDDINGS = True
except ImportError:
    HAS_EMBEDDINGS = False
    SentenceTransformer = None

try:
    from services.trading_engine.src.core.event_system import (
        EventBus, Event, EventType, EventPriority, get_event_bus,
    )

    HAS_EVENT_BUS = True
except ImportError:
    HAS_EVENT_BUS = False
    EventBus = None


# ---------------------------------------------------------------------------
# Enums and Data Classes
# ---------------------------------------------------------------------------

class AnalysisType(Enum):
    SIGNAL = "signal"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    MARKET = "market"
    STRATEGY = "strategy"


class AIConfidence(Enum):
    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()
    UNCERTAIN = auto()


@dataclass
class AIAnalysisResult:
    """Result of an AI analysis."""
    analysis_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    analysis_type: AnalysisType = AnalysisType.SIGNAL
    query: str = ""
    response: str = ""
    confidence: AIConfidence = AIConfidence.MEDIUM
    reasoning: str = ""
    recommendations: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ConversationMessage:
    """A conversation message for context management."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AIConfig:
    """Configuration for the AI assistant."""
    # LLM settings
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_api_key: Optional[str] = None

    # Embedding settings
    embedding_model: str = "snowflake-arctic-embed2:568m"
    embedding_dimension: int = 768

    # Qdrant settings
    qdrant_collection: str = "trading_knowledge"
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None

    # Behavior settings
    max_conversation_history: int = 50
    confidence_threshold: float = 0.7
    analysis_timeout_seconds: float = 30.0
    enable_rag: bool = True


# ---------------------------------------------------------------------------
# LLM Provider Abstraction
# ---------------------------------------------------------------------------

class LLMProvider:
    """Abstraction over LLM providers (OpenAI, local Ollama, etc.)."""

    def __init__(self, config: AIConfig):
        self._config = config
        self._client = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the LLM client."""
        if not HAS_OPENAI:
            logger.warning("openai package not available - LLM features will be simulated")
            return False

        api_key = self._config.llm_api_key
        if not api_key and HAS_LIBS:
            try:
                app_config = get_config()
                api_key = app_config.api.openai_api_key
            except Exception:
                pass

        if not api_key:
            logger.warning("No LLM API key configured - LLM features will be simulated")
            return False

        try:
            self._client = AsyncOpenAI(api_key=api_key)
            self._initialized = True
            logger.info("LLM provider initialized: %s", self._config.llm_model)
            return True
        except Exception as e:
            logger.error("Failed to initialize LLM provider: %s", e)
            return False

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Generate a response from the LLM."""
        if not self._initialized or not self._client:
            return None

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._config.llm_model,
                    messages=messages,
                    temperature=temperature or self._config.llm_temperature,
                    max_tokens=max_tokens or self._config.llm_max_tokens,
                ),
                timeout=self._config.analysis_timeout_seconds,
            )
            return response.choices[0].message.content
        except asyncio.TimeoutError:
            logger.error("LLM generation timed out")
            return None
        except Exception as e:
            logger.error("LLM generation error: %s", e)
            return None

    @property
    def is_available(self) -> bool:
        return self._initialized


# ---------------------------------------------------------------------------
# Embedding Provider
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """Local embedding generation using sentence-transformers."""

    def __init__(self, config: AIConfig):
        self._config = config
        self._model = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the embedding model."""
        if not HAS_EMBEDDINGS:
            logger.warning("sentence-transformers not available - embedding features disabled")
            return False

        try:
            self._model = SentenceTransformer(self._config.embedding_model)
            self._initialized = True
            logger.info("Embedding model initialized: %s", self._config.embedding_model)
            return True
        except Exception as e:
            logger.error("Failed to initialize embedding model: %s", e)
            return False

    def embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text."""
        if not self._initialized or not self._model:
            return None

        try:
            embedding = self._model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error("Embedding generation error: %s", e)
            return None

    def embed_batch(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Generate embeddings for multiple texts."""
        if not self._initialized or not self._model:
            return None

        try:
            embeddings = self._model.encode(texts)
            return embeddings.tolist()
        except Exception as e:
            logger.error("Batch embedding error: %s", e)
            return None

    @property
    def is_available(self) -> bool:
        return self._initialized


# ---------------------------------------------------------------------------
# Knowledge Store (Qdrant-backed)
# ---------------------------------------------------------------------------

class KnowledgeStore:
    """Vector store for trading knowledge and analysis history."""

    def __init__(self, config: AIConfig):
        self._config = config
        self._client: Any = None
        self._embedding_provider: Optional[EmbeddingProvider] = None
        self._collection_ready = False

    async def initialize(self, embedding_provider: EmbeddingProvider) -> bool:
        """Initialize the knowledge store."""
        self._embedding_provider = embedding_provider

        if HAS_QDRANT:
            try:
                if HAS_LIBS:
                    app_config = get_config()
                    self._client = QdrantClient(
                        url=self._config.qdrant_url or app_config.database.qdrant_url,
                        api_key=self._config.qdrant_api_key or app_config.database.qdrant_api_key,
                    )
                else:
                    self._client = QdrantClient(
                        url=self._config.qdrant_url or "http://localhost:6333",
                    )

                self._ensure_collection()
                self._collection_ready = True
                logger.info("Knowledge store initialized (Qdrant)")
                return True
            except Exception as e:
                logger.error("Failed to initialize Qdrant: %s", e)

        logger.warning("Qdrant not available - knowledge store disabled")
        return False

    def _ensure_collection(self):
        """Ensure the knowledge collection exists."""
        if not self._client:
            return

        try:
            collections = self._client.client.get_collections().collections
            names = [c.name for c in collections]
            if self._config.qdrant_collection not in names:
                self._client.create_collection(
                    collection_name=self._config.qdrant_collection,
                    vector_size=self._config.embedding_dimension,
                    distance="Cosine",
                )
                logger.info("Created Qdrant collection: %s", self._config.qdrant_collection)
        except Exception as e:
            logger.error("Failed to ensure collection: %s", e)

    async def store_analysis(self, analysis: AIAnalysisResult, text: str):
        """Store an analysis result for future retrieval."""
        if not self._collection_ready or not self._embedding_provider:
            return

        try:
            vector = self._embedding_provider.embed(text)
            if vector:
                self._client.upsert_vectors(
                    collection_name=self._config.qdrant_collection,
                    points=[{
                        "id": analysis.analysis_id,
                        "vector": vector,
                        "payload": {
                            "analysis_type": analysis.analysis_type.value,
                            "query": analysis.query,
                            "response": analysis.response,
                            "confidence": analysis.confidence.name,
                            "timestamp": analysis.timestamp.isoformat(),
                        },
                    }],
                )
        except Exception as e:
            logger.error("Failed to store analysis: %s", e)

    async def search_relevant(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant past analyses."""
        if not self._collection_ready or not self._embedding_provider:
            return []

        try:
            query_vector = self._embedding_provider.embed(query)
            if not query_vector:
                return []

            results = self._client.search(
                collection_name=self._config.qdrant_collection,
                query_vector=query_vector,
                limit=limit,
                score_threshold=0.6,
            )
            return results
        except Exception as e:
            logger.error("Knowledge search error: %s", e)
            return []

    @property
    def is_available(self) -> bool:
        return self._collection_ready


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TRADING_ASSISTANT = """You are an expert AI trading assistant for an algorithmic trading system.
You help traders and strategies with:

1. **Signal Analysis**: Evaluate trading signals considering market conditions, risk factors, and strategy context.
2. **Risk Assessment**: Analyze risk metrics and provide insights on portfolio risk, VaR, and exposure.
3. **Portfolio Analysis**: Comment on portfolio composition, diversification, and performance.
4. **Market Commentary**: Provide context on market conditions relevant to the user's positions.
5. **Strategy Suggestions**: Suggest strategy adjustments based on current conditions.

Guidelines:
- Be concise and data-driven in your analysis.
- Always mention key risk factors.
- Use confidence levels (HIGH/MEDIUM/LOW) for your assessments.
- Reference specific metrics when available.
- Never recommend trades that exceed the user's risk limits.
- Flag any concerns about unusual market conditions.
"""

SIGNAL_ANALYSIS_PROMPT = """Analyze the following trading signal:

Signal Details:
{signal_data}

Current Portfolio Context:
{portfolio_context}

Risk Metrics:
{risk_context}

Provide:
1. Signal quality assessment (confidence: HIGH/MEDIUM/LOW)
2. Key risk factors for this trade
3. Recommended position sizing considerations
4. Any concerns or caveats
"""

RISK_ASSESSMENT_PROMPT = """Assess the following risk situation:

Risk Context:
{risk_context}

Portfolio State:
{portfolio_context}

Recent Market Conditions:
{market_context}

Provide:
1. Overall risk assessment (confidence: HIGH/MEDIUM/LOW)
2. Key risk factors and their severity
3. Recommended risk mitigation actions
4. Any immediate concerns requiring attention
"""

PORTFOLIO_QUERY_PROMPT = """Answer the following question about the trading portfolio:

Question: {query}

Portfolio Context:
{portfolio_context}

Recent Activity:
{recent_activity}

Relevant Past Analysis:
{relevant_context}

Provide a clear, data-driven answer. Reference specific metrics and positions when possible.
"""


# ---------------------------------------------------------------------------
# AI Assistant Service
# ---------------------------------------------------------------------------

class AIAssistantService:
    """AI-powered trading assistant using LLMs and vector store.

    Subscribes to system events, provides AI analysis for signals,
    risk assessment, and natural language queries about the portfolio.
    """

    def __init__(self, config: Optional[AIConfig] = None):
        self._config = config or AIConfig()

        # Core components
        self._event_bus: Any = None
        self._llm_provider = LLMProvider(self._config)
        self._embedding_provider = EmbeddingProvider(self._config)
        self._knowledge_store = KnowledgeStore(self._config)
        self._kafka_producer: Any = None

        # State
        self._conversation_history: List[ConversationMessage] = []
        self._analysis_cache: Dict[str, AIAnalysisResult] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._health_checker: Any = None

        # Circuit breaker for LLM calls
        self._failure_count = 0
        self._failure_threshold = 5
        self._last_failure_time: Optional[float] = None
        self._recovery_timeout = 60.0
        self._circuit_open = False

        # Daily tracking
        self._analyses_today = 0
        self._last_reset_date = datetime.now(timezone.utc).date()

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize all AI assistant components."""
        try:
            # 1. Initialize event bus
            await self._init_event_bus()

            # 2. Initialize LLM provider
            llm_ok = await self._llm_provider.initialize()
            logger.info("LLM provider: %s", "ready" if llm_ok else "unavailable")

            # 3. Initialize embedding provider
            embedding_ok = self._embedding_provider.initialize()
            logger.info("Embedding provider: %s", "ready" if embedding_ok else "unavailable")

            # 4. Initialize knowledge store
            knowledge_ok = await self._knowledge_store.initialize(self._embedding_provider)
            logger.info("Knowledge store: %s", "ready" if knowledge_ok else "unavailable")

            # 5. Initialize Kafka producer
            await self._init_kafka_producer()

            # 6. Initialize health checker
            self._init_health_checker()

            # 7. Subscribe to events
            await self._subscribe_events()

            logger.info(
                "AI Assistant initialized (LLM=%s, Embeddings=%s, Knowledge=%s, Kafka=%s)",
                llm_ok, embedding_ok, knowledge_ok, HAS_KAFKA,
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize AI Assistant: %s", e)
            return False

    async def _init_event_bus(self):
        """Initialize event bus connection."""
        if HAS_EVENT_BUS:
            try:
                self._event_bus = get_event_bus()
                logger.info("Event bus connected")
            except Exception as e:
                logger.warning("Could not connect to event bus: %s", e)
        else:
            logger.warning("Event bus not available")

    async def _init_kafka_producer(self):
        """Initialize Kafka producer for publishing AI events."""
        if HAS_KAFKA:
            try:
                self._kafka_producer = get_kafka_producer()
                logger.info("Kafka producer initialized")
            except Exception as e:
                logger.warning("Could not initialize Kafka producer: %s", e)

    def _init_health_checker(self):
        """Initialize health check registration."""
        if HAS_LIBS:
            try:
                self._health_checker = HealthChecker()
                self._health_checker.register_check(
                    "llm_provider", self._check_llm_health
                )
                self._health_checker.register_check(
                    "knowledge_store", self._check_knowledge_health
                )
            except Exception as e:
                logger.warning("Could not initialize health checker: %s", e)

    async def _subscribe_events(self):
        """Subscribe to relevant system events."""
        if not self._event_bus:
            return

        if HAS_EVENT_BUS:
            self._event_bus.subscribe(EventType.SIGNAL, self._handle_signal_event)
            self._event_bus.subscribe(EventType.RISK_ALERT, self._handle_risk_alert_event)
            self._event_bus.subscribe(EventType.ORDER, self._handle_order_event)
            self._event_bus.subscribe(EventType.SYSTEM, self._handle_system_event)
            logger.info("Subscribed to event bus events")

    # -------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------

    async def _handle_signal_event(self, event: Any):
        """Handle incoming trading signal events."""
        try:
            data = event.data if hasattr(event, "data") else event
            if not isinstance(data, dict):
                return

            signal_type = data.get("signal_type", "").upper()
            symbol = data.get("symbol", data.get("instrument", ""))
            strength = data.get("strength", 0)

            logger.info("Analyzing signal: %s %s (strength=%.2f)", signal_type, symbol, strength)

            result = await self.analyze_signal(data)
            if result:
                self._analysis_cache[result.analysis_id] = result
                await self._publish_analysis(result)

        except Exception as e:
            logger.error("Error handling signal event: %s", e)

    async def _handle_risk_alert_event(self, event: Any):
        """Handle incoming risk alert events."""
        try:
            data = event.data if hasattr(event, "data") else event
            if not isinstance(data, dict):
                return

            severity = data.get("severity", "medium")
            message = data.get("message", "")

            if severity in ("high", "critical"):
                logger.warning("Processing critical risk alert: %s", message)
                result = await self.assess_risk(data)
                if result:
                    await self._publish_analysis(result)

        except Exception as e:
            logger.error("Error handling risk alert event: %s", e)

    async def _handle_order_event(self, event: Any):
        """Handle order events for context tracking."""
        try:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict):
                self._add_to_history("system", f"Order event: {json.dumps(data)[:200]}")
        except Exception as e:
            logger.error("Error handling order event: %s", e)

    async def _handle_system_event(self, event: Any):
        """Handle system events."""
        try:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict):
                action = data.get("action", "")
                if action == "shutdown":
                    await self.shutdown()
        except Exception as e:
            logger.error("Error handling system event: %s", e)

    # -------------------------------------------------------------------
    # Core AI Methods
    # -------------------------------------------------------------------

    async def analyze_signal(self, signal: Dict[str, Any]) -> Optional[AIAnalysisResult]:
        """Perform AI analysis on a trading signal.

        Args:
            signal: Signal data containing symbol, direction, indicators, etc.

        Returns:
            AIAnalysisResult with the analysis, or None if unavailable.
        """
        if not self._allow_llm_request():
            result = self._fallback_signal_analysis(signal)
            self._analyses_today += 1
            return result

        # Retrieve relevant past analyses for context
        relevant_context = ""
        if self._knowledge_store.is_available:
            symbol = signal.get("symbol", signal.get("instrument", ""))
            results = await self._knowledge_store.search_relevant(
                f"signal {symbol}", limit=3
            )
            if results:
                relevant_context = json.dumps([
                    {"query": r.get("payload", {}).get("query", ""),
                     "response": r.get("payload", {}).get("response", "")}
                    for r in results
                ], indent=2)[:1000]

        # Build analysis prompt
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TRADING_ASSISTANT},
            {"role": "user", "content": SIGNAL_ANALYSIS_PROMPT.format(
                signal_data=json.dumps(signal, indent=2, default=str),
                portfolio_context=self._get_portfolio_context(),
                risk_context=relevant_context or "No historical context available",
            )},
        ]

        response = await self._llm_provider.generate(messages)
        if response:
            confidence = self._parse_confidence(response)
            recommendations = self._parse_recommendations(response)
            risk_factors = self._parse_risk_factors(response)

            result = AIAnalysisResult(
                analysis_type=AnalysisType.SIGNAL,
                query=f"Signal analysis: {signal.get('symbol', '')} {signal.get('signal_type', '')}",
                response=response,
                confidence=confidence,
                reasoning=response[:500],
                recommendations=recommendations,
                risk_factors=risk_factors,
                metadata={"signal": signal},
            )

            # Store in knowledge base
            search_text = f"{signal.get('symbol', '')} {signal.get('signal_type', '')} {response[:200]}"
            await self._knowledge_store.store_analysis(result, search_text)

            self._record_success()
            self._analyses_today += 1

            return result

        self._record_failure()
        result = self._fallback_signal_analysis(signal)
        self._analyses_today += 1
        return result

    async def assess_risk(self, context: Dict[str, Any]) -> Optional[AIAnalysisResult]:
        """Perform AI-powered risk assessment.

        Args:
            context: Risk context data (positions, alerts, metrics).

        Returns:
            AIAnalysisResult with the risk assessment.
        """
        if not self._allow_llm_request():
            result = self._fallback_risk_assessment(context)
            self._analyses_today += 1
            return result

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_TRADING_ASSISTANT},
            {"role": "user", "content": RISK_ASSESSMENT_PROMPT.format(
                risk_context=json.dumps(context, indent=2, default=str),
                portfolio_context=self._get_portfolio_context(),
                market_context="Current market data not available in this context",
            )},
        ]

        response = await self._llm_provider.generate(messages)
        if response:
            result = AIAnalysisResult(
                analysis_type=AnalysisType.RISK,
                query=f"Risk assessment: {context.get('message', context.get('alert_type', ''))}",
                response=response,
                confidence=self._parse_confidence(response),
                reasoning=response[:500],
                recommendations=self._parse_recommendations(response),
                risk_factors=self._parse_risk_factors(response),
                metadata={"risk_context": context},
            )

            await self._knowledge_store.store_analysis(
                result, f"risk {context.get('alert_type', '')} {response[:200]}"
            )
            self._record_success()
            self._analyses_today += 1
            return result

        self._record_failure()
        result = self._fallback_risk_assessment(context)
        self._analyses_today += 1
        return result

    async def answer_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> AIAnalysisResult:
        """Answer a natural language query about the trading system.

        Args:
            query: User's natural language question.
            context: Optional additional context data.

        Returns:
            AIAnalysisResult with the answer.
        """
        self._add_to_history("user", query)

        # Retrieve relevant past context
        relevant_context = ""
        if self._knowledge_store.is_available:
            results = await self._knowledge_store.search_relevant(query, limit=5)
            if results:
                relevant_context = "\n".join([
                    f"- {r.get('payload', {}).get('response', '')[:300]}"
                    for r in results
                ])

        # Build conversation with history
        messages = [{"role": "system", "content": SYSTEM_PROMPT_TRADING_ASSISTANT}]

        # Add recent conversation history
        for msg in self._conversation_history[-10:]:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({
            "role": "user",
            "content": PORTFOLIO_QUERY_PROMPT.format(
                query=query,
                portfolio_context=self._get_portfolio_context(),
                recent_activity=self._get_recent_activity_summary(),
                relevant_context=relevant_context or "No relevant past analysis found.",
            ),
        })

        response_text = None
        if self._allow_llm_request():
            response_text = await self._llm_provider.generate(messages)
            if response_text:
                self._record_success()
            else:
                self._record_failure()

        if not response_text:
            response_text = self._fallback_query_response(query)

        result = AIAnalysisResult(
            analysis_type=AnalysisType.PORTFOLIO,
            query=query,
            response=response_text,
            confidence=AIConfidence.HIGH if response_text else AIConfidence.LOW,
            recommendations=self._parse_recommendations(response_text),
            metadata={"context": context or {}},
        )

        self._add_to_history("assistant", response_text)

        # Store query-answer pair
        await self._knowledge_store.store_analysis(result, f"{query} {response_text[:200]}")
        self._analyses_today += 1

        return result

    # -------------------------------------------------------------------
    # Fallback Methods (when LLM unavailable)
    # -------------------------------------------------------------------

    def _fallback_signal_analysis(self, signal: Dict[str, Any]) -> AIAnalysisResult:
        """Rule-based signal analysis when LLM is unavailable."""
        symbol = signal.get("symbol", signal.get("instrument", "UNKNOWN"))
        signal_type = signal.get("signal_type", "").upper()
        strength = signal.get("strength", 0)
        indicators = signal.get("indicators", {})

        risk_factors = []
        recommendations = []

        # Strength-based assessment
        if strength >= 0.8:
            confidence = AIConfidence.HIGH
            recommendations.append(f"Strong {signal_type} signal for {symbol}")
        elif strength >= 0.5:
            confidence = AIConfidence.MEDIUM
            recommendations.append(f"Moderate {signal_type} signal for {symbol} - consider reducing position size")
        else:
            confidence = AIConfidence.LOW
            recommendations.append(f"Weak {signal_type} signal for {symbol} - consider waiting for confirmation")
            risk_factors.append("Low signal strength")

        # Check for common risk indicators
        rsi = indicators.get("rsi", 0)
        if rsi > 70:
            risk_factors.append(f"RSI overbought ({rsi:.1f})")
        elif rsi < 30:
            risk_factors.append(f"RSI oversold ({rsi:.1f})")

        volatility = indicators.get("volatility", 0)
        if volatility > 0.03:
            risk_factors.append(f"High volatility ({volatility:.2%})")

        response = (
            f"Rule-based analysis for {symbol} {signal_type} signal "
            f"(strength={strength:.2f}): "
            f"{'Strong' if strength >= 0.8 else 'Moderate' if strength >= 0.5 else 'Weak'} signal. "
            f"Risk factors: {', '.join(risk_factors) if risk_factors else 'None identified'}. "
            f"(LLM unavailable - using rule-based fallback)"
        )

        return AIAnalysisResult(
            analysis_type=AnalysisType.SIGNAL,
            query=f"Signal analysis: {symbol} {signal_type}",
            response=response,
            confidence=confidence,
            reasoning=response,
            recommendations=recommendations,
            risk_factors=risk_factors,
            metadata={"signal": signal, "fallback": True},
        )

    def _fallback_risk_assessment(self, context: Dict[str, Any]) -> AIAnalysisResult:
        """Rule-based risk assessment when LLM is unavailable."""
        severity = context.get("severity", "medium")
        message = context.get("message", "Unknown risk event")
        limit_type = context.get("limit_type", "")

        risk_factors = [f"Alert: {message}"]
        if limit_type:
            risk_factors.append(f"Limit type: {limit_type}")

        recommendations = []
        if severity in ("high", "critical"):
            recommendations.append("Immediate attention required")
            recommendations.append("Consider reducing exposure")
        else:
            recommendations.append("Monitor the situation")

        response = (
            f"Rule-based risk assessment for '{message}' (severity={severity}): "
            f"{'CRITICAL' if severity == 'critical' else 'HIGH' if severity == 'high' else 'MEDIUM'} risk detected. "
            f"(LLM unavailable - using rule-based fallback)"
        )

        return AIAnalysisResult(
            analysis_type=AnalysisType.RISK,
            query=f"Risk assessment: {message}",
            response=response,
            confidence=AIConfidence.MEDIUM,
            recommendations=recommendations,
            risk_factors=risk_factors,
            metadata={"context": context, "fallback": True},
        )

    def _fallback_query_response(self, query: str) -> str:
        """Generate a basic response when LLM is unavailable."""
        q_lower = query.lower()

        if any(kw in q_lower for kw in ("position", "holding", "holding")):
            return (
                "Position data is available through the broker adapter. "
                "Please check the trading dashboard or query the position service directly. "
                "(LLM unavailable - detailed analysis not possible)"
            )
        elif any(kw in q_lower for kw in ("risk", "var", "drawdown", "exposure")):
            return (
                "Risk metrics are calculated by the risk engine. "
                "Current risk status can be viewed on the monitoring dashboard. "
                "(LLM unavailable - detailed analysis not possible)"
            )
        elif any(kw in q_lower for kw in ("signal", "strategy", "buy", "sell")):
            return (
                "Signal analysis requires the LLM provider. "
                "Rule-based signal evaluation is available but limited. "
                "(LLM unavailable - detailed analysis not possible)"
            )
        else:
            return (
                "I'm currently operating in limited mode without LLM access. "
                "Please try again when the LLM provider is available, or check "
                "the trading dashboard for real-time data. "
                "(LLM unavailable)"
            )

    # -------------------------------------------------------------------
    # Publishing
    # -------------------------------------------------------------------

    async def _publish_analysis(self, result: AIAnalysisResult):
        """Publish analysis result via event bus and Kafka."""
        # Publish via event bus
        if self._event_bus and HAS_EVENT_BUS:
            try:
                await self._event_bus.publish(Event(
                    type=EventType.SIGNAL,
                    data={
                        "analysis_id": result.analysis_id,
                        "analysis_type": result.analysis_type.value,
                        "confidence": result.confidence.name,
                        "response": result.response[:500],
                        "recommendations": result.recommendations[:5],
                        "risk_factors": result.risk_factors[:5],
                    },
                    priority=EventPriority.HIGH if result.confidence in (AIConfidence.LOW, AIConfidence.UNCERTAIN) else EventPriority.NORMAL,
                    source="ai_assistant",
                ))
            except Exception as e:
                logger.error("Failed to publish analysis via event bus: %s", e)

        # Publish via Kafka
        if self._kafka_producer and HAS_KAFKA:
            try:
                from libs.common.events.base import AIEvent
                event = AIEvent(
                    agent_id="ai_assistant",
                    query_id=uuid.uuid4(),
                    event_type="ai.analysis.completed",
                    metadata={
                        "analysis_id": result.analysis_id,
                        "analysis_type": result.analysis_type.value,
                        "confidence": result.confidence.name,
                    },
                )
                self._kafka_producer.produce_event("ai.analysis", event)
            except Exception as e:
                logger.error("Failed to publish analysis via Kafka: %s", e)

    # -------------------------------------------------------------------
    # Health Checks
    # -------------------------------------------------------------------

    async def _check_llm_health(self) -> Any:
        """Health check for LLM provider."""
        if HAS_LIBS:
            return HealthCheckResult(
                name="llm_provider",
                status=HealthStatus.HEALTHY if self._llm_provider.is_available else HealthStatus.DEGRADED,
                message="LLM provider operational" if self._llm_provider.is_available else "LLM provider unavailable - using fallbacks",
            )
        return None

    async def _check_knowledge_health(self) -> Any:
        """Health check for knowledge store."""
        if HAS_LIBS:
            status = HealthStatus.HEALTHY if self._knowledge_store.is_available else HealthStatus.DEGRADED
            return HealthCheckResult(
                name="knowledge_store",
                status=status,
                message="Knowledge store operational" if self._knowledge_store.is_available else "Knowledge store unavailable",
            )
        return None

    async def health_check(self) -> Dict[str, Any]:
        """Get overall service health status."""
        health = {
            "service": "ai_assistant",
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "llm_provider": self._llm_provider.is_available,
                "embedding_provider": self._embedding_provider.is_available,
                "knowledge_store": self._knowledge_store.is_available,
                "event_bus": self._event_bus is not None,
                "kafka": self._kafka_producer is not None,
            },
            "stats": {
                "analyses_today": self._analyses_today,
                "conversation_length": len(self._conversation_history),
                "cached_analyses": len(self._analysis_cache),
                "circuit_open": self._circuit_open,
            },
        }

        if not self._llm_provider.is_available:
            health["status"] = "degraded"

        # Run registered health checks
        if self._health_checker:
            try:
                check_results = await self._health_checker.run_checks()
                for name, result in check_results.items():
                    if result.status == HealthStatus.UNHEALTHY:
                        health["status"] = "unhealthy"
            except Exception:
                pass

        return health

    # -------------------------------------------------------------------
    # Circuit Breaker for LLM calls
    # -------------------------------------------------------------------

    def _allow_llm_request(self) -> bool:
        """Check if LLM request should be allowed (circuit breaker pattern)."""
        if not self._llm_provider.is_available:
            return False

        if self._circuit_open:
            if self._last_failure_time and (time.time() - self._last_failure_time) >= self._recovery_timeout:
                self._circuit_open = False
                self._failure_count = 0
                logger.info("LLM circuit breaker: recovered")
                return True
            return False

        return True

    def _record_success(self):
        """Record successful LLM call."""
        self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self):
        """Record failed LLM call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._circuit_open = True
            logger.warning("LLM circuit breaker opened after %d failures", self._failure_count)

    # -------------------------------------------------------------------
    # Context Helpers
    # -------------------------------------------------------------------

    def _get_portfolio_context(self) -> str:
        """Build portfolio context string for prompts."""
        if self._conversation_history:
            # Extract any known portfolio data from conversation
            return f"Conversation history available ({len(self._conversation_history)} messages)"
        return "No portfolio context available"

    def _get_recent_activity_summary(self) -> str:
        """Summarize recent activity from conversation history."""
        if not self._conversation_history:
            return "No recent activity"

        recent = self._conversation_history[-5:]
        return "\n".join([
            f"[{msg.role}] {msg.content[:100]}"
            for msg in recent
        ])

    def _add_to_history(self, role: str, content: str):
        """Add message to conversation history."""
        self._conversation_history.append(ConversationMessage(role=role, content=content))

        # Trim if too long
        if len(self._conversation_history) > self._config.max_conversation_history:
            self._conversation_history = self._conversation_history[-self._config.max_conversation_history:]

    # -------------------------------------------------------------------
    # Response Parsing Utilities
    # -------------------------------------------------------------------

    def _parse_confidence(self, response: str) -> AIConfidence:
        """Parse confidence level from LLM response."""
        response_lower = response.lower()
        if "confidence: high" in response_lower or "high confidence" in response_lower:
            return AIConfidence.HIGH
        elif "confidence: low" in response_lower or "low confidence" in response_lower:
            return AIConfidence.LOW
        elif "confidence: uncertain" in response_lower or "uncertain" in response_lower:
            return AIConfidence.UNCERTAIN
        return AIConfidence.MEDIUM

    def _parse_recommendations(self, response: str) -> List[str]:
        """Extract recommendations from LLM response."""
        recommendations = []
        in_section = False

        for line in response.split("\n"):
            stripped = line.strip()
            if "recommend" in stripped.lower() and ":" in stripped:
                in_section = True
                continue
            if in_section and stripped.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
                rec = stripped.lstrip("-*•0123456789. ").strip()
                if rec:
                    recommendations.append(rec)
            elif in_section and stripped and not stripped.startswith(("-", "*", "•")):
                in_section = False

        return recommendations[:5]

    def _parse_risk_factors(self, response: str) -> List[str]:
        """Extract risk factors from LLM response."""
        risk_factors = []
        in_section = False

        for line in response.split("\n"):
            stripped = line.strip()
            if "risk factor" in stripped.lower() and ":" in stripped:
                in_section = True
                continue
            if in_section and stripped.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
                factor = stripped.lstrip("-*•0123456789. ").strip()
                if factor:
                    risk_factors.append(factor)
            elif in_section and stripped and not stripped.startswith(("-", "*", "•")):
                in_section = False

        return risk_factors[:5]

    # -------------------------------------------------------------------
    # Startup / Shutdown
    # -------------------------------------------------------------------

    async def run(self):
        """Main service loop."""
        self._running = True
        logger.info("AI Assistant service running...")

        while self._running and not self._shutdown_event.is_set():
            try:
                # Reset daily counters at midnight
                today = datetime.now(timezone.utc).date()
                if today > self._last_reset_date:
                    self._analyses_today = 0
                    self._last_reset_date = today

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in AI assistant main loop: %s", e)
                await asyncio.sleep(5)

        logger.info("AI Assistant service stopped")

    async def shutdown(self):
        """Gracefully shut down the service."""
        logger.info("Shutting down AI Assistant...")
        self._running = False
        self._shutdown_event.set()

        # Flush Kafka producer
        if self._kafka_producer and HAS_KAFKA:
            try:
                self._kafka_producer.close()
            except Exception as e:
                logger.error("Error closing Kafka producer: %s", e)

        logger.info("AI Assistant shutdown complete")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_ai_assistant: Optional[AIAssistantService] = None


def get_ai_assistant() -> AIAssistantService:
    """Get the global AI assistant singleton."""
    global _ai_assistant
    if _ai_assistant is None:
        _ai_assistant = AIAssistantService()
    return _ai_assistant


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

async def main():
    """Service entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("Starting AI Assistant Service...")

    # Load config
    config = AIConfig(
        llm_api_key=os.getenv("OPENAI_API_KEY"),
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
    )

    service = AIAssistantService(config)
    initialized = await service.initialize()

    if not initialized:
        logger.warning("AI Assistant initialized with limited capabilities")

    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
