"""Unit tests for SectorClassifier and RiskEngine sector-exposure aggregation.

Covers the previously-stubbed concentration-risk path: prior to this the risk
engine returned a hardcoded {"Unclassified": 1.0}, making sector concentration
limits non-functional. These tests pin the real behaviour:

- SectorClassifier: classification (known/unknown/case), custom maps, and
  dollar-weighted sector aggregation.
- RiskEngine._calculate_sector_exposures: end-to-end aggregation using injected
  prices, including multi-sector weighting, short positions, and empty inputs.
"""

import pytest
from risk_engines import RiskConfig, RiskEngine, SectorClassifier

# ---------------------------------------------------------------------------
# SectorClassifier: classification
# ---------------------------------------------------------------------------

class TestSectorClassifierClassify:
    def test_known_symbol(self):
        sc = SectorClassifier()
        assert sc.classify("AAPL") == "Information Technology"
        assert sc.classify("JPM") == "Financials"
        assert sc.classify("XOM") == "Energy"

    def test_case_insensitive(self):
        sc = SectorClassifier()
        assert sc.classify("aapl") == sc.classify("AAPL")
        assert sc.classify("Jpm") == "Financials"

    def test_unknown_symbol_falls_back(self):
        sc = SectorClassifier()
        assert sc.classify("ZZZZ") == "Unclassified"

    def test_empty_symbol_falls_back(self):
        sc = SectorClassifier()
        assert sc.classify("") == "Unclassified"

    def test_custom_unknown_bucket(self):
        sc = SectorClassifier(unknown_sector="Other")
        assert sc.classify("ZZZZ") == "Other"

    def test_payment_networks_are_financials(self):
        """V/MA follow the 2023 GICS reclassification into Financials."""
        sc = SectorClassifier()
        assert sc.classify("V") == "Financials"
        assert sc.classify("MA") == "Financials"

    def test_coverage_is_positive(self):
        assert SectorClassifier().coverage > 50


# ---------------------------------------------------------------------------
# SectorClassifier: custom maps
# ---------------------------------------------------------------------------

class TestSectorClassifierCustomMap:
    def test_merge_extends_defaults(self):
        sc = SectorClassifier({"FOO": "Custom Sector"})
        assert sc.classify("FOO") == "Custom Sector"
        # Defaults still present
        assert sc.classify("AAPL") == "Information Technology"

    def test_merge_can_override_default(self):
        sc = SectorClassifier({"AAPL": "Reclassified"})
        assert sc.classify("AAPL") == "Reclassified"

    def test_no_merge_uses_only_supplied(self):
        sc = SectorClassifier({"FOO": "Custom"}, merge_defaults=False)
        assert sc.classify("FOO") == "Custom"
        assert sc.classify("AAPL") == "Unclassified"
        assert sc.coverage == 1

    def test_custom_map_keys_normalized(self):
        sc = SectorClassifier({"foo": "Custom"}, merge_defaults=False)
        assert sc.classify("FOO") == "Custom"


# ---------------------------------------------------------------------------
# SectorClassifier: sector_exposures
# ---------------------------------------------------------------------------

class TestSectorClassifierExposures:
    def test_single_sector_sums_to_one(self):
        sc = SectorClassifier()
        exposures = sc.sector_exposures({"AAPL": 10_000.0, "MSFT": 30_000.0})
        assert exposures == {"Information Technology": pytest.approx(1.0)}

    def test_multi_sector_weighting(self):
        sc = SectorClassifier()
        # IT 10k, Financials 30k -> 0.25 / 0.75
        exposures = sc.sector_exposures({"AAPL": 10_000.0, "JPM": 30_000.0})
        assert exposures["Information Technology"] == pytest.approx(0.25)
        assert exposures["Financials"] == pytest.approx(0.75)

    def test_absolute_value_used_for_shorts(self):
        sc = SectorClassifier()
        # A short still consumes sector capacity (absolute market value).
        exposures = sc.sector_exposures({"AAPL": 10_000.0, "MSFT": -10_000.0})
        assert exposures == {"Information Technology": pytest.approx(1.0)}

    def test_unknown_symbols_aggregate_into_fallback(self):
        sc = SectorClassifier()
        exposures = sc.sector_exposures({"AAPL": 10_000.0, "ZZZZ": 10_000.0})
        assert exposures["Information Technology"] == pytest.approx(0.5)
        assert exposures["Unclassified"] == pytest.approx(0.5)

    def test_empty_input(self):
        assert SectorClassifier().sector_exposures({}) == {}

    def test_zero_total_value(self):
        assert SectorClassifier().sector_exposures({"AAPL": 0.0, "MSFT": 0.0}) == {}

    def test_exposures_sum_to_one(self):
        sc = SectorClassifier()
        exposures = sc.sector_exposures(
            {"AAPL": 5_000.0, "JPM": 7_000.0, "XOM": 3_000.0, "ZZZZ": 1_000.0}
        )
        assert sum(exposures.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RiskEngine integration
# ---------------------------------------------------------------------------

class TestRiskEngineSectorExposures:
    @pytest.mark.asyncio
    async def test_default_engine_has_classifier(self, risk_engine):
        assert isinstance(risk_engine._sector_classifier, SectorClassifier)

    @pytest.mark.asyncio
    async def test_empty_positions(self, risk_engine):
        assert await risk_engine._calculate_sector_exposures({}) == {}

    @pytest.mark.asyncio
    async def test_dollar_weighted_aggregation(self, risk_engine):
        # Inject deterministic prices via the price cache (read first by
        # _get_current_price, so the broker mock is bypassed).
        risk_engine._price_cache = {"AAPL": 100.0, "MSFT": 100.0, "JPM": 200.0}
        # AAPL 100sh@100 = 10k (IT), MSFT 100sh@100 = 10k (IT), JPM 100sh@200 = 20k (Fin)
        positions = {"AAPL": 100.0, "MSFT": 100.0, "JPM": 100.0}
        exposures = await risk_engine._calculate_sector_exposures(positions)
        assert exposures["Information Technology"] == pytest.approx(0.5)
        assert exposures["Financials"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_short_positions_count_absolute(self, risk_engine):
        risk_engine._price_cache = {"AAPL": 100.0, "MSFT": 100.0}
        positions = {"AAPL": 100.0, "MSFT": -100.0}
        exposures = await risk_engine._calculate_sector_exposures(positions)
        assert exposures == {"Information Technology": pytest.approx(1.0)}

    @pytest.mark.asyncio
    async def test_unknown_symbol_unclassified(self, risk_engine):
        risk_engine._price_cache = {"AAPL": 100.0, "ZZZZ": 100.0}
        positions = {"AAPL": 100.0, "ZZZZ": 100.0}
        exposures = await risk_engine._calculate_sector_exposures(positions)
        assert exposures["Unclassified"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_all_prices_zero_returns_empty(self, risk_engine):
        risk_engine._price_cache = {"AAPL": 0.0}
        assert await risk_engine._calculate_sector_exposures({"AAPL": 100.0}) == {}

    @pytest.mark.asyncio
    async def test_injected_classifier_is_used(self, mock_broker_adapter, event_bus):
        engine = RiskEngine(
            broker_adapter=mock_broker_adapter,
            event_bus=event_bus,
            config=RiskConfig(),
            sector_classifier=SectorClassifier(
                {"AAPL": "TechBucket"}, merge_defaults=False
            ),
        )
        engine._price_cache = {"AAPL": 100.0}
        exposures = await engine._calculate_sector_exposures({"AAPL": 100.0})
        assert exposures == {"TechBucket": pytest.approx(1.0)}
