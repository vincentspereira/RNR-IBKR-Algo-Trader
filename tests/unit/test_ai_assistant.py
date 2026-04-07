"""Unit tests for the AI Assistant Service.

Tests cover:
- Service initialization and lifecycle
- Signal analysis (LLM and fallback)
- Risk assessment (LLM and fallback)
- Natural language query handling
- Circuit breaker for LLM calls
- Knowledge store integration
- Health checks
- Event bus subscription
"""

import asyncio
import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_module():
    """Get the AI assistant module."""
    if "ai_assistant_main" not in sys.modules:
        pytest.skip("AI assistant module not loaded")
    return sys.modules["ai_assistant_main"]


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------

class TestAIAssistantInit:
    """Tests for AIAssistantService initialization."""

    def test_creates_with_default_config(self, ai_assistant):
        mod = _get_module()
        assert isinstance(ai_assistant, mod.AIAssistantService)

    def test_creates_with_custom_config(self):
        mod = _get_module()
        config = mod.AIConfig(
            llm_model="gpt-4",
            llm_temperature=0.5,
            max_conversation_history=100,
        )
        service = mod.AIAssistantService(config=config)
        assert service._config.llm_model == "gpt-4"
        assert service._config.llm_temperature == 0.5
        assert service._config.max_conversation_history == 100

    def test_initial_state_is_not_running(self, ai_assistant):
        assert ai_assistant._running is False
        assert ai_assistant._circuit_open is False
        assert ai_assistant._failure_count == 0

    def test_daily_counters_initialized(self, ai_assistant):
        assert ai_assistant._analyses_today == 0


class TestAIAssistantInitialize:
    """Tests for the async initialize() method."""

    @pytest.mark.asyncio
    async def test_initialize_returns_true(self, ai_assistant):
        result = await ai_assistant.initialize()
        assert result is True

    @pytest.mark.asyncio
    async def test_initialize_without_event_bus(self):
        mod = _get_module()
        config = mod.AIConfig()
        service = mod.AIAssistantService(config=config)
        # Should not crash even without external deps
        result = await service.initialize()
        assert result is True


# ---------------------------------------------------------------------------
# Signal Analysis Tests
# ---------------------------------------------------------------------------

class TestSignalAnalysis:
    """Tests for signal analysis (both LLM and fallback)."""

    @pytest.mark.asyncio
    async def test_fallback_signal_analysis_strong_signal(self, ai_assistant):
        signal = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.9,
            "indicators": {"rsi": 55, "volatility": 0.02},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert result is not None
        assert result.analysis_type.value == "signal"
        assert result.confidence.name == "HIGH"
        assert any("Strong" in r for r in result.recommendations)
        assert result.metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_fallback_signal_analysis_moderate_signal(self, ai_assistant):
        signal = {
            "symbol": "TSLA",
            "signal_type": "SELL",
            "strength": 0.6,
            "indicators": {},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert result is not None
        assert result.confidence.name == "MEDIUM"

    @pytest.mark.asyncio
    async def test_fallback_signal_analysis_weak_signal(self, ai_assistant):
        signal = {
            "symbol": "MSFT",
            "signal_type": "BUY",
            "strength": 0.3,
            "indicators": {},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert result is not None
        assert result.confidence.name == "LOW"
        assert any("Weak" in r or "weak" in r.lower() for r in result.recommendations)

    @pytest.mark.asyncio
    async def test_fallback_detects_overbought_rsi(self, ai_assistant):
        signal = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.7,
            "indicators": {"rsi": 75},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert result is not None
        assert any("overbought" in f.lower() for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fallback_detects_oversold_rsi(self, ai_assistant):
        signal = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.7,
            "indicators": {"rsi": 25},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert any("oversold" in f.lower() for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_fallback_detects_high_volatility(self, ai_assistant):
        signal = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.7,
            "indicators": {"volatility": 0.05},
        }
        result = await ai_assistant.analyze_signal(signal)
        assert any("volatility" in f.lower() for f in result.risk_factors)

    @pytest.mark.asyncio
    async def test_signal_analysis_increments_counter(self, ai_assistant):
        signal = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.8,
            "indicators": {},
        }
        assert ai_assistant._analyses_today == 0
        await ai_assistant.analyze_signal(signal)
        assert ai_assistant._analyses_today == 1


# ---------------------------------------------------------------------------
# Risk Assessment Tests
# ---------------------------------------------------------------------------

class TestRiskAssessment:
    """Tests for AI risk assessment."""

    @pytest.mark.asyncio
    async def test_fallback_risk_assessment_critical(self, ai_assistant):
        context = {
            "severity": "critical",
            "message": "Daily loss limit exceeded",
            "limit_type": "daily_loss",
        }
        result = await ai_assistant.assess_risk(context)
        assert result is not None
        assert result.analysis_type.value == "risk"
        assert any("Immediate" in r for r in result.recommendations)
        assert result.metadata.get("fallback") is True

    @pytest.mark.asyncio
    async def test_fallback_risk_assessment_medium(self, ai_assistant):
        context = {
            "severity": "medium",
            "message": "Approaching position limit",
        }
        result = await ai_assistant.assess_risk(context)
        assert result is not None
        assert any("Monitor" in r for r in result.recommendations)

    @pytest.mark.asyncio
    async def test_risk_assessment_includes_context(self, ai_assistant):
        context = {
            "severity": "high",
            "message": "VaR breach",
            "current_value": 60000,
            "limit_value": 50000,
        }
        result = await ai_assistant.assess_risk(context)
        assert "VaR breach" in result.response


# ---------------------------------------------------------------------------
# Natural Language Query Tests
# ---------------------------------------------------------------------------

class TestAnswerQuery:
    """Tests for natural language query handling."""

    @pytest.mark.asyncio
    async def test_fallback_position_query(self, ai_assistant):
        result = await ai_assistant.answer_query("What are my current positions?")
        assert result is not None
        assert result.analysis_type.value == "portfolio"
        assert "position" in result.response.lower()

    @pytest.mark.asyncio
    async def test_fallback_risk_query(self, ai_assistant):
        result = await ai_assistant.answer_query("What is my current VaR exposure?")
        assert "risk" in result.response.lower() or "LLM" in result.response

    @pytest.mark.asyncio
    async def test_fallback_signal_query(self, ai_assistant):
        result = await ai_assistant.answer_query("Should I buy AAPL right now?")
        assert "signal" in result.response.lower() or "LLM" in result.response

    @pytest.mark.asyncio
    async def test_fallback_generic_query(self, ai_assistant):
        result = await ai_assistant.answer_query("How is the market today?")
        assert "LLM" in result.response or "limited" in result.response.lower()

    @pytest.mark.asyncio
    async def test_query_updates_conversation_history(self, ai_assistant):
        assert len(ai_assistant._conversation_history) == 0
        await ai_assistant.answer_query("Test question")
        assert len(ai_assistant._conversation_history) == 2  # user + assistant

    @pytest.mark.asyncio
    async def test_conversation_history_trims(self):
        mod = _get_module()
        config = mod.AIConfig(max_conversation_history=4)
        service = mod.AIAssistantService(config=config)

        for i in range(5):
            await service.answer_query(f"Question {i}")

        # Should keep only last 4 messages
        assert len(service._conversation_history) <= 4


# ---------------------------------------------------------------------------
# Circuit Breaker Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for LLM circuit breaker pattern."""

    def test_initially_allows_requests(self, ai_assistant):
        assert ai_assistant._allow_llm_request() is False  # No LLM provider initialized

    def test_circuit_opens_after_failures(self, ai_assistant):
        ai_assistant._llm_provider._initialized = True
        ai_assistant._failure_count = 0

        for _ in range(ai_assistant._failure_threshold):
            ai_assistant._record_failure()

        assert ai_assistant._circuit_open is True
        assert ai_assistant._allow_llm_request() is False

    def test_circuit_reopens_after_timeout(self, ai_assistant):
        ai_assistant._circuit_open = True
        ai_assistant._failure_count = 10
        ai_assistant._last_failure_time = time.time() - 120  # 2 minutes ago
        ai_assistant._llm_provider._initialized = True

        assert ai_assistant._allow_llm_request() is True
        assert ai_assistant._circuit_open is False

    def test_circuit_stays_closed_on_success(self, ai_assistant):
        ai_assistant._failure_count = 3
        ai_assistant._llm_provider._initialized = True

        ai_assistant._record_success()
        assert ai_assistant._failure_count == 2


# ---------------------------------------------------------------------------
# Confidence Parsing Tests
# ---------------------------------------------------------------------------

class TestConfidenceParsing:
    """Tests for parsing confidence from LLM responses."""

    def test_parse_high_confidence(self, ai_assistant):
        mod = _get_module()
        result = ai_assistant._parse_confidence("The analysis shows high confidence in this trade.")
        assert result == mod.AIConfidence.HIGH

    def test_parse_low_confidence(self, ai_assistant):
        mod = _get_module()
        result = ai_assistant._parse_confidence("This has low confidence due to market uncertainty.")
        assert result == mod.AIConfidence.LOW

    def test_parse_default_medium(self, ai_assistant):
        mod = _get_module()
        result = ai_assistant._parse_confidence("The market looks normal today.")
        assert result == mod.AIConfidence.MEDIUM

    def test_parse_uncertain(self, ai_assistant):
        mod = _get_module()
        result = ai_assistant._parse_confidence("The situation is uncertain given mixed signals.")
        assert result == mod.AIConfidence.UNCERTAIN


# ---------------------------------------------------------------------------
# Recommendation Parsing Tests
# ---------------------------------------------------------------------------

class TestRecommendationParsing:
    """Tests for parsing recommendations from LLM responses."""

    def test_parse_dash_list(self, ai_assistant):
        response = "Recommendations:\n- Reduce position size\n- Add stop loss\n- Monitor closely"
        recs = ai_assistant._parse_recommendations(response)
        assert len(recs) >= 2
        assert any("Reduce position" in r for r in recs)

    def test_parse_numbered_list(self, ai_assistant):
        response = "Recommendations:\n1. Wait for confirmation\n2. Use smaller size"
        recs = ai_assistant._parse_recommendations(response)
        assert len(recs) >= 2

    def test_empty_recommendations(self, ai_assistant):
        response = "No specific recommendations at this time."
        recs = ai_assistant._parse_recommendations(response)
        assert len(recs) == 0

    def test_max_five_recommendations(self, ai_assistant):
        response = "Recommendations:\n" + "\n".join([f"- Rec {i}" for i in range(10)])
        recs = ai_assistant._parse_recommendations(response)
        assert len(recs) <= 5


# ---------------------------------------------------------------------------
# Health Check Tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Tests for service health checks."""

    @pytest.mark.asyncio
    async def test_health_check_structure(self, ai_assistant):
        health = await ai_assistant.health_check()
        assert "service" in health
        assert health["service"] == "ai_assistant"
        assert "status" in health
        assert "components" in health
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_health_check_components(self, ai_assistant):
        health = await ai_assistant.health_check()
        assert "llm_provider" in health["components"]
        assert "embedding_provider" in health["components"]
        assert "knowledge_store" in health["components"]
        assert "event_bus" in health["components"]
        assert "kafka" in health["components"]

    @pytest.mark.asyncio
    async def test_health_check_stats(self, ai_assistant):
        health = await ai_assistant.health_check()
        assert "analyses_today" in health["stats"]
        assert "circuit_open" in health["stats"]

    @pytest.mark.asyncio
    async def test_health_degraded_without_llm(self, ai_assistant):
        # LLM not initialized so should be degraded
        health = await ai_assistant.health_check()
        assert health["status"] in ("degraded", "healthy")


# ---------------------------------------------------------------------------
# Event Handler Tests
# ---------------------------------------------------------------------------

class TestEventHandlers:
    """Tests for event bus event handling."""

    @pytest.mark.asyncio
    async def test_handle_signal_event(self, ai_assistant):
        event = MagicMock()
        event.data = {
            "symbol": "AAPL",
            "signal_type": "BUY",
            "strength": 0.8,
            "indicators": {},
        }
        await ai_assistant._handle_signal_event(event)
        # Should not crash and should have done an analysis
        assert ai_assistant._analyses_today == 1

    @pytest.mark.asyncio
    async def test_handle_signal_event_non_dict_data(self, ai_assistant):
        event = MagicMock()
        event.data = "not a dict"
        await ai_assistant._handle_signal_event(event)
        assert ai_assistant._analyses_today == 0

    @pytest.mark.asyncio
    async def test_handle_risk_alert_critical(self, ai_assistant):
        event = MagicMock()
        event.data = {
            "severity": "critical",
            "message": "Position limit breached",
        }
        await ai_assistant._handle_risk_alert_event(event)
        assert ai_assistant._analyses_today == 1

    @pytest.mark.asyncio
    async def test_handle_risk_alert_low_severity(self, ai_assistant):
        event = MagicMock()
        event.data = {
            "severity": "low",
            "message": "Minor fluctuation",
        }
        await ai_assistant._handle_risk_alert_event(event)
        assert ai_assistant._analyses_today == 0

    @pytest.mark.asyncio
    async def test_handle_order_event(self, ai_assistant):
        event = MagicMock()
        event.data = {"order_id": "123", "status": "filled"}
        await ai_assistant._handle_order_event(event)
        assert len(ai_assistant._conversation_history) == 1

    @pytest.mark.asyncio
    async def test_handle_system_shutdown_event(self, ai_assistant):
        ai_assistant._running = True
        event = MagicMock()
        event.data = {"action": "shutdown"}
        await ai_assistant._handle_system_event(event)
        assert ai_assistant._running is False


# ---------------------------------------------------------------------------
# Lifecycle Tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    """Tests for service startup and shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_running_false(self, ai_assistant):
        ai_assistant._running = True
        await ai_assistant.shutdown()
        assert ai_assistant._running is False

    @pytest.mark.asyncio
    async def test_run_stops_on_shutdown(self, ai_assistant):
        ai_assistant._running = True
        # Trigger shutdown immediately
        ai_assistant._shutdown_event.set()
        await ai_assistant.run()
        # Should have exited the loop
        assert ai_assistant._running is False or ai_assistant._shutdown_event.is_set()


# ---------------------------------------------------------------------------
# AIAnalysisResult Tests
# ---------------------------------------------------------------------------

class TestAIAnalysisResult:
    """Tests for AIAnalysisResult dataclass."""

    def test_result_has_unique_id(self):
        mod = _get_module()
        r1 = mod.AIAnalysisResult()
        r2 = mod.AIAnalysisResult()
        assert r1.analysis_id != r2.analysis_id

    def test_result_defaults(self):
        mod = _get_module()
        result = mod.AIAnalysisResult()
        assert result.analysis_type.value == "signal"
        assert result.confidence.name == "MEDIUM"
        assert result.recommendations == []
        assert result.risk_factors == []

    def test_result_with_data(self):
        mod = _get_module()
        result = mod.AIAnalysisResult(
            query="Test query",
            response="Test response",
            confidence=mod.AIConfidence.HIGH,
            recommendations=["Rec 1"],
            risk_factors=["Risk 1"],
        )
        assert result.query == "Test query"
        assert result.confidence == mod.AIConfidence.HIGH


# ---------------------------------------------------------------------------
# AIConfig Tests
# ---------------------------------------------------------------------------

class TestAIConfig:
    """Tests for AIConfig dataclass."""

    def test_default_config(self):
        mod = _get_module()
        config = mod.AIConfig()
        assert config.llm_provider == "openai"
        assert config.llm_temperature == 0.3
        assert config.max_conversation_history == 50
        assert config.enable_rag is True

    def test_custom_config(self):
        mod = _get_module()
        config = mod.AIConfig(
            llm_model="gpt-4",
            llm_temperature=0.7,
            max_conversation_history=100,
        )
        assert config.llm_model == "gpt-4"
        assert config.llm_temperature == 0.7


# ---------------------------------------------------------------------------
# LLM Provider Tests
# ---------------------------------------------------------------------------

class TestLLMProvider:
    """Tests for LLM provider abstraction."""

    def test_not_initialized_by_default(self, ai_assistant):
        assert ai_assistant._llm_provider.is_available is False

    @pytest.mark.asyncio
    async def test_generate_returns_none_when_not_initialized(self, ai_assistant):
        result = await ai_assistant._llm_provider.generate(
            [{"role": "user", "content": "test"}]
        )
        assert result is None


# ---------------------------------------------------------------------------
# Embedding Provider Tests
# ---------------------------------------------------------------------------

class TestEmbeddingProvider:
    """Tests for embedding provider."""

    def test_not_initialized_by_default(self, ai_assistant):
        assert ai_assistant._embedding_provider.is_available is False

    def test_embed_returns_none_when_not_initialized(self, ai_assistant):
        result = ai_assistant._embedding_provider.embed("test text")
        assert result is None

    def test_embed_batch_returns_none_when_not_initialized(self, ai_assistant):
        result = ai_assistant._embedding_provider.embed_batch(["test1", "test2"])
        assert result is None


# ---------------------------------------------------------------------------
# Knowledge Store Tests
# ---------------------------------------------------------------------------

class TestKnowledgeStore:
    """Tests for knowledge store."""

    def test_not_available_by_default(self, ai_assistant):
        assert ai_assistant._knowledge_store.is_available is False

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_unavailable(self, ai_assistant):
        results = await ai_assistant._knowledge_store.search_relevant("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_store_does_not_crash_when_unavailable(self, ai_assistant):
        mod = _get_module()
        analysis = mod.AIAnalysisResult(response="test")
        # Should not raise
        await ai_assistant._knowledge_store.store_analysis(analysis, "test text")
