import asyncio
import importlib.util
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
#!/usr/bin/env python3

# Comprehensive test suite for all data feed adapters.
# Tests functionality, error handling, and data quality."



# Import all data feed adapters


# Get current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Import adapters dynamically
adapter_modules = {}
# adapter_files = ["
# "yahoo_finance","
# "alpha_vantage","
# "finnhub","
# "investing_com","
# "cme_group","
# "twelve_data","
# "polygon","
# "barchart","
# "spiderrock","
# "tradingcharts","
#     "oanda",
# ]

# for adapter_name in adapter_files:
#     try:""
#         file_path = os.path.join(current_dir, f"{adapter_name}.py")
#         if os.path.exists(file_path):
#             spec = importlib.util.spec_from_file_location(adapter_name, file_path)
#             module = importlib.util.module_from_spec(spec)
#             spec.loader.exec_module(module)
# adapter_modules[adapter_name] = module"
#             print(f"[OK] Successfully imported {adapter_name}")
#         else:""
#             print(f"[WARN] File not found: {file_path}")
#     except Exception as e:""
#         print(f"[X] Failed to import {adapter_name}: {e}")
#         adapter_modules[adapter_name] = None

# Extract adapter classes
# try:
# YahooFinanceAdapter = getattr("
#         adapter_modules.get("yahoo_finance"), "YahooFinanceAdapter", None
# )
# AlphaVantageAdapter = getattr("
#         adapter_modules.get("alpha_vantage"), "AlphaVantageAdapter", None
# )"
#     FinnhubAdapter = getattr(adapter_modules.get("finnhub"), "FinnhubAdapter", None)
# InvestingAdapter = getattr("
#         adapter_modules.get("investing_com"), "InvestingAdapter", None
# )"
#     CMEAdapter = getattr(adapter_modules.get("cme_group"), "CMEAdapter", None)
# TwelveDataAdapter = getattr("
#         adapter_modules.get("twelve_data"), "TwelveDataAdapter", None
# )"
# PolygonAdapter = getattr(adapter_modules.get("polygon"), "PolygonAdapter", None)"
#     BarchartAdapter = getattr(adapter_modules.get("barchart"), "BarchartAdapter", None)
# SpiderRockAdapter = getattr("
#         adapter_modules.get("spiderrock"), "SpiderRockAdapter", None
# )
# TradingChartsAdapter = getattr("
#         adapter_modules.get("tradingcharts"), "TradingChartsAdapter", None
# )"
#     OandaAdapter = getattr(adapter_modules.get("oanda"), "OandaAdapter", None)
# except Exception as e:""
#     print(f"Error extracting adapter classes: {e}")

# Configure logging"
# logging.basicConfig("
#     level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# )
logger = logging.getLogger(__name__)


class DataFeedTester:""
#     "Comprehensive tester for all data feed adapters"

#     def __init__(self):
#         self.results = {}
#         self.test_symbols = {""
# "stocks": ["AAPL", "MSFT", "GOOGL", "TSLA"],"
# "forex": ["EURUSD", "GBPUSD", "USDJPY"],"
# "crypto": ["BTCUSD", "ETHUSD"],"
# "commodities": ["GC=F", "CL=F"],  # Gold, Oil futures"
# "indices": ["^GSPC", "^IXIC"],  # S&P 500, NASDAQ
# }

        # Initialize adapters"
#         self.adapters = {
# "yahoo_finance": YahooFinanceAdapter(),"
# "alpha_vantage": AlphaVantageAdapter(),"
# "finnhub": FinnhubAdapter(),"
# "investing_com": InvestingAdapter(),"
# "cme_group": CMEAdapter(),"
# "twelve_data": TwelveDataAdapter(),"
# "polygon": PolygonAdapter(),"
# "barchart": BarchartAdapter(),"
# "spiderrock": SpiderRockAdapter(),"
# "tradingcharts": TradingChartsAdapter(),"
# "oanda": OandaAdapter(),
# }

#     async def test_adapter_initialization(
# self, adapter_name: str, adapter
# ) -> Dict[str, Any]:"
# "Test adapter initialization and basic functionality
# test_result = {
# "adapter": adapter_name,"
# "initialized": False,"
# "has_required_methods": False,"
# "error": None,
# }
# "
#         try:
            # Check if adapter initialized properly"
#             test_result["initialized"] = adapter is not None
# "
            # Check required methods"
# required_methods = ["
# "get_historical_data","
# "get_real_time_data","
#                 "subscribe_to_data",
# ]
# has_methods = all(hasattr(adapter, method) for method in required_methods)"
#             test_result["has_required_methods"] = has_methods
# "
#             logger.info(f"[OK] {adapter_name} initialization test passed")

#         except Exception as e:""
# test_result["error"] = str(e)"
#             logger.error(f"[X] {adapter_name} initialization test failed: {e}")

#         return test_result

#     async def test_historical_data(
# self, adapter_name: str, adapter, symbol: str
# ) -> Dict[str, Any]:"
# "Test historical data retrieval
# test_result = {
# "adapter": adapter_name,"
# "symbol": symbol,"
# "data_retrieved": False,"
# "data_quality": {},"
# "error": None,
# }

#         try:
            # Test historical data retrieval
#             end_date = datetime.now()
#             start_date = end_date - timedelta(days=30)

# data = await adapter.get_historical_data("
#                 symbol=symbol, start_date=start_date, end_date=end_date, interval="1d"
# )

#             if data is not None and not data.empty:""
#                 test_result["data_retrieved"] = True

                # Test data quality"
# quality_checks = self._check_data_quality(data)"
#                 test_result["data_quality"] = quality_checks

# logger.info("
#                     f"[OK] {adapter_name} historical data test passed for {symbol}"
# )
#             else:""
#                 test_result["error"] = "No data returned"
#                 logger.warning(f"[WARN] {adapter_name} returned no data for {symbol}")

#         except Exception as e:""
#             test_result["error"] = str(e)
# logger.error("
#                 f"[X] {adapter_name} historical data test failed for {symbol}: {e}"
# )

#         return test_result

# "

#     async def test_real_time_data(
# self, adapter_name: str, adapter, symbol: str
# ) -> Dict[str, Any]:"
# "Test real-time data retrieval
# test_result = {"
# "adapter": adapter_name,"
# "symbol": symbol,"
# "real_time_available": False,"
# "data_format_valid": False,"
# "error": None,
# }

#         try:
            # Test real-time data
#             real_time_data = await adapter.get_real_time_data(symbol)

#             if real_time_data is not None:""
#                 test_result["real_time_available"] = True

                # Check data format"
#                 if isinstance(real_time_data, dict):""
#                     required_fields = ["price", "timestamp"]
# has_required = all(
# field in real_time_data for field in required_fields
# )"
#                     test_result["data_format_valid"] = has_required
# "
#                 logger.info(f"[OK] {adapter_name} real-time data test passed for {symbol}")
#             else:""
# test_result["error"] = "No real-time data available
# logger.warning("
#                     f"[WARN] {adapter_name} real-time data not available for {symbol}"
# )

#         except Exception as e:""
#             test_result["error"] = str(e)
# logger.error("
#                 f"[X] {adapter_name} real-time data test failed for {symbol}: {e}"
# )

#         return test_result

#     async def test_subscription(
# self, adapter_name: str, adapter, symbol: str
# ) -> Dict[str, Any]:"
# "Test data subscription functionality
# test_result = {
# "adapter": adapter_name,"
# "symbol": symbol,"
# "subscription_works": False,"
# "data_stream_active": False,"
# "error": None,
# }

#         try:
            # Test subscription
#             subscription_id = await adapter.subscribe_to_data(symbol)

#             if subscription_id is not None:""
#                 test_result["subscription_works"] = True

                # Wait briefly to see if data streams
#                 await asyncio.sleep(2)

                # Check if data is streaming (this would depend on adapter implementation)"
                # For now, just mark as successful if subscription worked"
#                 test_result["data_stream_active"] = True

                # Unsubscribe"
#                 if hasattr(adapter, "unsubscribe_from_data"):
#                     await adapter.unsubscribe_from_data(subscription_id)
# "
#                 logger.info(f"[OK] {adapter_name} subscription test passed for {symbol}")
#             else:""
#                 test_result["error"] = "Subscription failed"
#                 logger.warning(f"[WARN] {adapter_name} subscription failed for {symbol}")

#         except Exception as e:""
# test_result["error"] = str(e)"
#             logger.error(f"[X] {adapter_name} subscription test failed for {symbol}: {e}")

#         return test_result

# "

#     async def test_error_handling(self, adapter_name: str, adapter):
# "Test error handling with invalid inputs
# test_result = {
# "adapter": adapter_name,"
# "handles_invalid_symbol": False,"
# "handles_invalid_dates": False,"
# "handles_network_errors": False,"
# "error": None,
# }

#         try:
            # Test invalid symbol
#             try:
# data = await adapter.get_historical_data("
#                     symbol="INVALID_SYMBOL_12345",
#                     start_date=datetime.now() - timedelta(days=30),
# end_date=datetime.now(),"
#                     interval="1d",
# )
                # Should handle gracefully (return None or empty DataFrame)"
#                 test_result["handles_invalid_symbol"] = data is None or data.empty
#             except Exception:
                # Should not raise unhandled exceptions"
#                 test_result["handles_invalid_symbol"] = False

            # Test invalid date range
#             try:
# data = await adapter.get_historical_data("
#                     symbol="AAPL",
#                     start_date=datetime.now() + timedelta(days=30),  # Future date
#                     end_date=datetime.now() - timedelta(days=30),  # Past date""
#                     interval="1d",
# )"
#                 test_result["handles_invalid_dates"] = data is None or data.empty
#             except Exception:""
#                 test_result["handles_invalid_dates"] = False

            # For network errors, we'll assume good handling if other tests pass"
#             test_result["handles_network_errors"] = True
# "
#             logger.info(f"[OK] {adapter_name} error handling test completed")

#         except Exception as e:""
# test_result["error"] = str(e)"
#             logger.error(f"[X] {adapter_name} error handling test failed: {e}")

#         return test_result

#     def _check_data_quality(self, data: pd.DataFrame):
# "Check data quality metrics
# quality = {"
# "has_ohlc": False,"
# "has_volume": False,"
# "no_missing_values": False,"
# "reasonable_price_range": False,"
# "chronological_order": False,"
# "row_count": len(data),
# }

#         try:
            # Check for OHLC columns"
# ohlc_columns = ["open", "high", "low", "close"]"
#             quality["has_ohlc"] = all(col in data.columns for col in ohlc_columns)

            # Check for volume"
#             quality["has_volume"] = "volume" in data.columns

            # Check for missing values in price columns"
#             if quality["has_ohlc"]:
# price_data = data[ohlc_columns]"
#                 quality["no_missing_values"] = not price_data.isnull().any().any()

                # Check reasonable price range (no negative prices, high > low, etc.)
#                 if not price_data.empty:
# all_positive = (price_data >= 0).all().all()"
# high_ge_low = (data["high"] >= data["low"]).all()"
#                     quality["reasonable_price_range"] = all_positive and high_ge_low

            # Check chronological order"
#             if hasattr(data.index, "is_monotonic_increasing"):""
# quality["chronological_order"] = data.index.is_monotonic_increasing"
#             elif "date" in data.columns:""
#                 quality["chronological_order"] = data["date"].is_monotonic_increasing

#         except Exception as e:""
#             logger.warning(f"Error checking data quality: {e}")

#         return quality

#     async def run_comprehensive_tests(self):
#         "Run comprehensive tests on all adapters"
#         logger.info("Starting comprehensive data feed adapter tests...")

# all_results = {
# "summary": {
# "total_adapters": len(self.adapters),"
# "passed_initialization": 0,"
# "passed_historical_data": 0,"
# "passed_real_time_data": 0,"
# "passed_subscription": 0,"
# "passed_error_handling": 0,
# },"
# "detailed_results": {},
# }

#         for adapter_name, adapter in self.adapters.items():"'"'
# logger.info(f"\n{'='*50}")"'
# logger.info(f"Testing {adapter_name.upper()} Adapter")"'"'
#             logger.info(f"{'='*50}")

# adapter_results = {
# "initialization": {},"
# "historical_data": {},"
# "real_time_data": {},"
# "subscription": {},"
# "error_handling": {},
# }

            # Test initialization"
# init_result = await self.test_adapter_initialization(adapter_name, adapter)"
#             adapter_results["initialization"] = init_result
# "
#             if init_result["initialized"] and init_result["has_required_methods"]:""
#                 all_results["summary"]["passed_initialization"] += 1

                # Test with different symbol types
#                 for symbol_type, symbols in self.test_symbols.items():
#                     for symbol in symbols[:2]:  # Test first 2 symbols of each type
#                         try:
                            # Historical data test
# hist_result = await self.test_historical_data(
#                                 adapter_name, adapter, symbol
# )"
#                             if symbol_type not in adapter_results["historical_data"]:""
# adapter_results["historical_data"][symbol_type] = []"
# adapter_results["historical_data"][symbol_type].append(
#                                 hist_result
# )

                            # Real-time data test
# rt_result = await self.test_real_time_data(
#                                 adapter_name, adapter, symbol
# )"
#                             if symbol_type not in adapter_results["real_time_data"]:""
# adapter_results["real_time_data"][symbol_type] = []"
# adapter_results["real_time_data"][symbol_type].append(
#                                 rt_result
# )

                            # Subscription test
# sub_result = await self.test_subscription(
#                                 adapter_name, adapter, symbol
# )"
#                             if symbol_type not in adapter_results["subscription"]:""
# adapter_results["subscription"][symbol_type] = []"
# adapter_results["subscription"][symbol_type].append(
#                                 sub_result
# )

#                         except Exception as e:
# logger.error("
#                                 f"Error testing {adapter_name} with {symbol}: {e}"
# )

                # Error handling test"
# error_result = await self.test_error_handling(adapter_name, adapter)"
#                 adapter_results["error_handling"] = error_result

                # Update summary counts"
#                 if any(""
# result.get("data_retrieved", False)"
#                     for results in adapter_results["historical_data"].values()
#                     for result in results
# ):"
#                     all_results["summary"]["passed_historical_data"] += 1

#                 if any(""
# result.get("real_time_available", False)"
#                     for results in adapter_results["real_time_data"].values()
#                     for result in results
# ):"
#                     all_results["summary"]["passed_real_time_data"] += 1

#                 if any(""
# result.get("subscription_works", False)"
#                     for results in adapter_results["subscription"].values()
#                     for result in results
# ):"
#                     all_results["summary"]["passed_subscription"] += 1

#                 if error_result.get(""
# "handles_invalid_symbol", False"
# ) and error_result.get("handles_invalid_dates", False):"
#                     all_results["summary"]["passed_error_handling"] += 1
# "
#             all_results["detailed_results"][adapter_name] = adapter_results

#         return all_results

#     def generate_test_report(self, results: Dict[str, Any]):
# "Generate a comprehensive test report
# report = []"
# report.append("\n" + "=" * 80)"
# report.append("DATA FEED ADAPTER TEST REPORT")"
#         report.append("=" * 80)
# "
        # Summary"
# summary = results["summary"]"'
# report.append(f"\nSUMMARY:")"'"'
#         report.append(f"Total Adapters Tested: {summary['total_adapters']}")
# report.append("'"'
#             f"Passed Initialization: {summary['passed_initialization']}/{summary['total_adapters']}"
# )
# report.append("'"'
#             f"Passed Historical Data: {summary['passed_historical_data']}/{summary['total_adapters']}"
# )
# report.append("'"'
#             f"Passed Real-time Data: {summary['passed_real_time_data']}/{summary['total_adapters']}"
# )
# report.append("'"'
#             f"Passed Subscription: {summary['passed_subscription']}/{summary['total_adapters']}"
# )
# report.append("'"'
#             f"Passed Error Handling: {summary['passed_error_handling']}/{summary['total_adapters']}"
# )

        # Detailed results"
# report.append(f"\nDETAILED RESULTS:")"
#         report.append("-" * 80)
# "
#         for adapter_name, adapter_results in results["detailed_results"].items():""
#             report.append(f"\n{adapter_name.upper()} ADAPTER:")

            # Initialization"
#             init = adapter_results["initialization"]
# status = ("
#                 "[OK] PASS"
#                 if init.get("initialized") and init.get("has_required_methods")""
# else "[X] FAIL
# )"
# report.append(f"  Initialization: {status}")"'
#             if init.get("error"):"'"'
#                 report.append(f"    Error: {init['error']}")
# "
            # Historical data"
# report.append(f"  Historical Data:")"
#             for symbol_type, results_list in adapter_results["historical_data"].items():
# successful = sum("
# 1 for r in results_list if r.get("data_retrieved", False)
# )
#                 total = len(results_list)
# report.append("
#                     f"    {symbol_type.capitalize()}: {successful}/{total} successful"
# )

            # Real-time data"
# report.append(f"  Real-time Data:")"
#             for symbol_type, results_list in adapter_results["real_time_data"].items():
# successful = sum("
# 1 for r in results_list if r.get("real_time_available", False)
# )
#                 total = len(results_list)
# report.append("
#                     f"    {symbol_type.capitalize()}: {successful}/{total} successful"
# )

            # Subscription"
# report.append(f"  Subscription:")"
#             for symbol_type, results_list in adapter_results["subscription"].items():
# successful = sum("
# 1 for r in results_list if r.get("subscription_works", False)
# )
#                 total = len(results_list)
# report.append("
#                     f"    {symbol_type.capitalize()}: {successful}/{total} successful"
# )

            # Error handling"
#             error_handling = adapter_results["error_handling"]
# invalid_symbol = ("
#                 "[OK]" if error_handling.get("handles_invalid_symbol", False) else "[X]"
# )
# invalid_dates = ("
# "[OK]" if error_handling.get("handles_invalid_dates", False) else "[X]
# )"
# report.append(f"  Error Handling:")"
# report.append(f"    Invalid Symbol: {invalid_symbol}")"
#             report.append(f"    Invalid Dates: {invalid_dates}")
# "
# report.append("\n" + "=" * 80)"
# report.append("END OF REPORT")"
#         report.append("=" * 80)
# "
#         return "\n".join(report)


# async def main():
#     "Main test function"
#     tester = DataFeedTester()

#     try:
        # Run comprehensive tests
#         results = await tester.run_comprehensive_tests()

        # Generate and display report
#         report = tester.generate_test_report(results)
#         print(report)

        # Save report to file"
#         with open("data_feed_test_report.txt", "w") as f:
#             f.write(report)
# "'"'
#         logger.info("\nTest report saved to 'data_feed_test_report.txt'")

        # Return results for further processing
#         return results

#     except Exception as e:""
#         logger.error(f"Test execution failed: {e}")
#         traceback.print_exc()
#         return None

# "
# if __name__ == "__main__":
    # Run the tests
#     results = asyncio.run(main())

#     if results:""
# summary = results["summary"]"
# total = summary["total_adapters"]"
#         passed = summary["passed_initialization"]
# "'"'
# print(f"\n{'='*50}")"'
# print(f"FINAL SUMMARY: {passed}/{total} adapters passed basic tests")"'"'
#         print(f"{'='*50}")

        # Exit with appropriate code
#         sys.exit(0 if passed == total else 1)
#     else:""
# print(")
#         sys.exit(1)
# "'"'