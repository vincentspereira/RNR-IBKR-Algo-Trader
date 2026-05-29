"""Verify all quant dependencies imported successfully after poetry install."""
modules = [
    "numpy", "pandas", "scipy", "statsmodels", "arch", "hmmlearn",
    "filterpy", "cvxpy", "sklearn", "xgboost", "lightgbm", "catboost",
    "mlflow", "polars", "vectorbt", "empyrical", "quantstats",
    "stable_baselines3", "gymnasium", "pandas_ta", "tsfresh",
    "confluent_kafka.schema_registry", "pingouin", "linearmodels", "pypfopt",
]
ok = []
fail = []
for m in modules:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append(f"{m}: {type(e).__name__}: {str(e)[:80]}")
print(f"OK ({len(ok)}/{len(modules)}):", ", ".join(ok))
print()
if fail:
    print(f"FAIL ({len(fail)}):")
    for f in fail:
        print(" ", f)
