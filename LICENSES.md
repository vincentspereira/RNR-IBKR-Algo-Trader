# Dependency License Audit -- IBKR Algo Trader

**Audit date:** 2026-05-21
**Auditor:** Automated dependency review
**Scope:** All Python packages declared in `pyproject.toml`, root `requirements.txt`, `services/*/requirements.txt`, `libs/*/pyproject.toml`, and every Docker image in `docker-compose.yml`.
**Audience purpose:** The owner plans to lift selected features into a separate **closed-source commercial product ("MAS")**. This document classifies every dependency by whether such a lift-and-ship is legally permissible without source disclosure.

> ASCII-only output per workspace style. Plain "OK" / "NO" / "CONDITIONAL" / "VERIFY" used instead of glyphs.

---

## 0. Changes Applied After Audit (2026-05-21)

The following docker-compose changes were applied in this session to address commercial-merge risks identified in section 3. Sections 3.6, 3.7, 3.20, 3.21 below are now partially stale; this section is the new source of truth.

| Service | Before | After | Why |
|---|---|---|---|
| Graph DB | `neo4j:5.25-community` (GPL-3.0) | `arcadedata/arcadedb:24.11.1` (Apache-2.0) | ArcadeDB is multi-model (graph + document + KV + time-series), supports Cypher/Gremlin/SQL, single service. Apache-2.0 is fully MAS-merge-safe. |
| Cache / pub-sub | `redis:7.4-alpine` (SSPL-1.0 + RSALv2) | `valkey/valkey:8-alpine` (BSD-3-Clause) | Valkey is the Linux Foundation fork of Redis 7.2. Wire-compatible — Python `redis` package works unchanged. |
| Grafana | `grafana/grafana:10.2.3` (AGPL-3.0) | `grafana/grafana:9.5.21` (Apache-2.0) | Pinned at last Apache-2.0 release. Future migration target: **Perses** (Apache-2.0, CNCF) when its data-source maturity matches. |
| Loki | `grafana/loki:2.9.3` (Apache-2.0) | `grafana/loki:2.9.10` (Apache-2.0) | Stayed on 2.9.x, latest patch. v3+ moved to AGPL-3.0. Future migration target: **Vector (MPL-2.0) → ClickHouse** to remove a service entirely. |
| Promtail | `grafana/promtail:2.9.3` (Apache-2.0) | `grafana/promtail:2.9.10` (Apache-2.0) | Same reasoning as Loki. |

Code paths affected (not changed in this session, tracked in HANDOVER.md):

- `libs/database/neo4j/client.py` — uses Neo4j Bolt driver. Must rewrite to use ArcadeDB HTTP API or `arcadedb-python` client. Not on the paper-trading critical path.
- `libs/database/redis/client.py`, `core_trading/data_feeds/institutional_data_feed_manager.py`, `tests/unit/test_database.py` — these use the `redis` Python package. No changes needed; Valkey is wire-compatible.
- `infrastructure/neo4j/init/` directory needs to be renamed to `infrastructure/arcadedb/init/` and its Cypher scripts adapted to ArcadeDB's slightly different Cypher dialect (most syntax is identical).

Still pending (called out in section 3, will be addressed in future sessions if needed):

- `confluentinc/cp-kafka:7.7.0` and `confluentinc/cp-schema-registry:7.7.0` use **Confluent Community License** — fine for internal use, restricts SaaS resale. Migration target: `apache/kafka:3.9.0` (Apache-2.0) and `apicurio/apicurio-registry` (Apache-2.0).
- `yfinance` (Apache-2.0 code, but Yahoo ToS prohibits commercial scraping) — must swap to Polygon / Tiingo / IEX Cloud / Finnhub before any commercial MAS deployment.

---

## 1. License Glossary

### MIT
Extremely permissive. Allows commercial use, modification, distribution, sublicensing, and private use. Only obligation is to retain the original copyright notice and license text in copies or substantial portions of the software. **Commercial-closed-source merge: YES.**

### BSD-2-Clause / BSD-3-Clause
Functionally equivalent to MIT for commercial purposes. Must retain copyright notice, license text, and disclaimer. The 3-clause variant additionally forbids using the original author's name for endorsement. **Commercial-closed-source merge: YES.**

### Apache-2.0
Permissive, business-friendly. Allows commercial use, modification, distribution, patent grant (explicit), and sublicensing. Must retain NOTICE file if present, mark modified files, and include the license text. Patent retaliation clause activates if you sue an Apache contributor. **Commercial-closed-source merge: YES (with attribution).**

### MPL-2.0 (Mozilla Public License)
Weak copyleft at the **file level**. You may combine MPL files with proprietary code in a larger work, but any modification you make to an MPL-licensed file itself must be released under MPL-2.0. You do NOT need to release proprietary files that merely link to or use MPL code. **Commercial-closed-source merge: CONDITIONAL -- safe if you do not modify the MPL files themselves.**

### LGPL-2.1 / LGPL-3.0
Weak copyleft at the **library level**. You may dynamically link to LGPL code from closed-source applications. If you statically link, modify the library, or otherwise create a "work based on the library," the resulting library code must remain LGPL and users must be able to relink with a modified version. In Python, `pip install` and `import` are considered **dynamic linking**, so a closed-source app that imports an LGPL package is legally fine, provided you (a) ship the library as a separable component, (b) include the LGPL license text, and (c) do not modify the library source itself (or, if you do, publish those modifications under LGPL). **Commercial-closed-source merge: CONDITIONAL.**

### GPL-2.0 / GPL-3.0
Strong copyleft. Any "derivative work" that incorporates GPL code must itself be released under GPL when distributed. In Python, importing a GPL package generally creates a derivative work, so a closed-source product that ships GPL Python code is **non-compliant**. There is a network-services carve-out: GPL does NOT trigger merely because users *interact* with the program over a network -- only redistribution of binaries/source does. So you can run GPL software server-side (e.g., Neo4j Community as a separate process) without contaminating your closed-source client, but you cannot embed GPL libraries inside your distributed product. **Commercial-closed-source merge: NO if embedded/linked; YES if used purely as an out-of-process server you do not redistribute.**

### AGPL-3.0
Strongest copyleft on the market. Same as GPL-3.0 PLUS a network clause: if users interact with the program **over a network**, you must offer them the complete corresponding source code of your modified version. There is **no SaaS loophole**. AGPL contamination is the single biggest risk for any SaaS or hosted commercial product. **Commercial-closed-source merge: NO -- avoid entirely for any product you intend to host or sell.**

### SSPL-1.0 / RSALv2 (Redis 7.4+, MongoDB, Elastic)
Source-Available, NOT OSI-open-source. **SSPL** requires that anyone offering the software "as a service" release the entire service stack (management, monitoring, automation) under SSPL. **RSALv2** forbids offering the software as a managed/hosted service to third parties and forbids removing license/IP notices. Both licenses *permit* internal use, embedding inside a non-competing product, and on-premise deployment to your own customers. They forbid building a Redis-as-a-Service / DBaaS offering. **Commercial-closed-source merge: CONDITIONAL -- fine for internal use or embedded use; forbidden if you resell the database itself as a managed service.**

### PostgreSQL License
A permissive MIT-style license specific to PostgreSQL. Allows commercial use, modification, redistribution, all without source disclosure. **Commercial-closed-source merge: YES.**

### Proprietary / Commercial
Terms are dictated by the vendor's specific license agreement. Must be reviewed case-by-case. **Commercial-closed-source merge: VERIFY contract.**

---

## 2. Direct Dependencies

Versions reflect the minimum/upper bounds declared in the project files. License columns reflect the **upstream package license** as published on PyPI / GitHub as of audit date. "Safe?" = Commercial-Merge-Safe for closed-source MAS.

### 2a. Root `pyproject.toml` (`[tool.poetry.dependencies]`)

| Package | Version | License | Source | Safe? |
|---|---|---|---|---|
| python | ^3.11 | PSF (BSD-style) | https://docs.python.org/3/license.html | YES |
| pydantic | ^2.5.0 | MIT | https://pypi.org/project/pydantic/ | YES |
| pydantic-settings | ^2.1.0 | MIT | https://pypi.org/project/pydantic-settings/ | YES |
| fastapi | ^0.109.0 | MIT | https://pypi.org/project/fastapi/ | YES |
| uvicorn[standard] | ^0.25.0 | BSD-3-Clause | https://pypi.org/project/uvicorn/ | YES |
| sqlalchemy | ^2.0.25 | MIT | https://pypi.org/project/SQLAlchemy/ | YES |
| alembic | ^1.13.1 | MIT | https://pypi.org/project/alembic/ | YES |
| psycopg2-binary | ^2.9.9 | LGPL-3.0-or-later (with OpenSSL exception) | https://pypi.org/project/psycopg2-binary/ | CONDITIONAL (LGPL) |
| asyncpg | ^0.29.0 | Apache-2.0 | https://pypi.org/project/asyncpg/ | YES |
| clickhouse-driver | ^0.2.6 | MIT | https://pypi.org/project/clickhouse-driver/ | YES |
| clickhouse-connect | ^0.6.23 | Apache-2.0 | https://pypi.org/project/clickhouse-connect/ | YES |
| neo4j | ^5.16.0 (Python driver) | Apache-2.0 | https://pypi.org/project/neo4j/ | YES -- driver only; see Neo4j server note |
| redis (python client) | ^5.0.1 | MIT | https://pypi.org/project/redis/ | YES |
| hiredis | ^2.3.2 | BSD-3-Clause | https://pypi.org/project/hiredis/ | YES |
| qdrant-client | ^1.7.0 | Apache-2.0 | https://pypi.org/project/qdrant-client/ | YES |
| kafka-python | ^2.0.2 | Apache-2.0 | https://pypi.org/project/kafka-python/ | YES |
| confluent-kafka[avro] | ^2.3.0 | Apache-2.0 | https://pypi.org/project/confluent-kafka/ | YES |
| avro | ^1.11.3 | Apache-2.0 | https://pypi.org/project/avro/ | YES |
| prometheus-client | ^0.19.0 | Apache-2.0 | https://pypi.org/project/prometheus-client/ | YES |
| structlog | ^24.1.0 | Apache-2.0 / MIT (dual) | https://pypi.org/project/structlog/ | YES |
| python-json-logger | ^2.0.7 | BSD-2-Clause | https://pypi.org/project/python-json-logger/ | YES |
| pyjwt[crypto] | ^2.8.0 | MIT | https://pypi.org/project/PyJWT/ | YES |
| cryptography | ^41.0.7 | Apache-2.0 OR BSD-3-Clause (dual) | https://pypi.org/project/cryptography/ | YES |
| python-keycloak | ^3.9.0 | MIT | https://pypi.org/project/python-keycloak/ | YES |
| python-dotenv | ^1.0.0 | BSD-3-Clause | https://pypi.org/project/python-dotenv/ | YES |
| httpx | ^0.26.0 | BSD-3-Clause | https://pypi.org/project/httpx/ | YES |
| tenacity | ^8.2.3 | Apache-2.0 | https://pypi.org/project/tenacity/ | YES |
| pytest | ^7.4.3 | MIT | https://pypi.org/project/pytest/ | YES (dev only) |
| pytest-cov | ^4.1.0 | MIT | https://pypi.org/project/pytest-cov/ | YES (dev only) |
| pytest-asyncio | ^0.21.1 | Apache-2.0 | https://pypi.org/project/pytest-asyncio/ | YES (dev only) |
| pytest-mock | ^3.12.0 | MIT | https://pypi.org/project/pytest-mock/ | YES (dev only) |
| faker | ^22.0.0 | MIT | https://pypi.org/project/Faker/ | YES (dev only) |
| black | ^23.12.1 | MIT | https://pypi.org/project/black/ | YES (dev only) |
| isort | ^5.13.2 | MIT | https://pypi.org/project/isort/ | YES (dev only) |
| mypy | ^1.8.0 | MIT | https://pypi.org/project/mypy/ | YES (dev only) |
| pylint | ^3.0.3 | GPL-2.0 | https://pypi.org/project/pylint/ | YES (dev only -- not distributed) |
| pre-commit | ^3.6.0 | MIT | https://pypi.org/project/pre-commit/ | YES (dev only) |

### 2b. Root `requirements.txt` (additional / overlapping)

| Package | Version | License | Source | Safe? |
|---|---|---|---|---|
| **nautilus-trader** | >=1.190.0 | **LGPL-3.0-or-later** | https://github.com/nautechsystems/nautilus_trader/blob/develop/LICENSE.md | CONDITIONAL -- dynamic-link OK |
| vectorbt | >=0.25.0 | Apache-2.0 (note: vectorbt PRO is commercial) | https://github.com/polakowo/vectorbt | YES (community edition) |
| ta-lib (Python wrapper) | >=0.4.25 | BSD-2-Clause | https://github.com/TA-Lib/ta-lib-python | YES (underlying C lib is also BSD) |
| ta | >=0.10.2 | MIT | https://pypi.org/project/ta/ | YES |
| quantlib (QuantLib-Python) | >=1.32 | BSD-3-Clause (modified) | https://www.quantlib.org/license.shtml | YES |
| riskfolio-lib | >=4.3.0 | BSD-3-Clause | https://github.com/dcajasn/Riskfolio-Lib | YES |
| pyportfolioopt | >=1.5.5 | MIT | https://pypi.org/project/PyPortfolioOpt/ | YES |
| yfinance | >=0.2.18 | Apache-2.0 | https://pypi.org/project/yfinance/ | YES (but Yahoo ToS prohibits commercial scraping -- see Action Items) |
| alpha-vantage | >=2.3.1 | MIT | https://pypi.org/project/alpha-vantage/ | YES (API ToS separate) |
| finnhub-python | >=2.4.18 | Apache-2.0 | https://pypi.org/project/finnhub-python/ | YES |
| ib-insync | >=0.9.86 | BSD-2-Clause | https://github.com/erdewit/ib_insync | YES |
| ccxt | >=4.2.25 | MIT | https://pypi.org/project/ccxt/ | YES |
| pandas-datareader | >=0.10.0 | BSD-3-Clause | https://pypi.org/project/pandas-datareader/ | YES |
| langchain | >=0.1.0 | MIT | https://pypi.org/project/langchain/ | YES |
| langchain-community | >=0.0.13 | MIT | https://pypi.org/project/langchain-community/ | YES |
| langchain-openai | >=0.0.5 | MIT | https://pypi.org/project/langchain-openai/ | YES |
| **langgraph** | >=0.0.20 | MIT | https://github.com/langchain-ai/langgraph/blob/main/LICENSE | YES (LangGraph Platform/Cloud is separate commercial) |
| openai | >=1.12.0 | Apache-2.0 | https://pypi.org/project/openai/ | YES (API ToS separate) |
| anthropic | >=0.8.1 | MIT | https://pypi.org/project/anthropic/ | YES (API ToS separate) |
| transformers | >=4.36.2 | Apache-2.0 | https://pypi.org/project/transformers/ | YES |
| torch | >=2.1.2 | BSD-3-Clause | https://pypi.org/project/torch/ | YES |
| tensorflow | >=2.15.0 | Apache-2.0 | https://pypi.org/project/tensorflow/ | YES |
| scikit-learn | >=1.4.0 | BSD-3-Clause | https://pypi.org/project/scikit-learn/ | YES |
| xgboost | >=2.0.3 | Apache-2.0 | https://pypi.org/project/xgboost/ | YES |
| lightgbm | >=4.3.0 | MIT | https://pypi.org/project/lightgbm/ | YES |
| catboost | >=1.2.2 | Apache-2.0 | https://pypi.org/project/catboost/ | YES |
| shap | >=0.44.1 | MIT | https://pypi.org/project/shap/ | YES |
| optuna | >=3.5.0 | MIT | https://pypi.org/project/optuna/ | YES |
| pandas | >=2.2.0 | BSD-3-Clause | https://pypi.org/project/pandas/ | YES |
| numpy | >=1.26.3 | BSD-3-Clause | https://pypi.org/project/numpy/ | YES |
| polars | >=0.20.6 | MIT | https://pypi.org/project/polars/ | YES |
| pyarrow | >=15.0.0 | Apache-2.0 | https://pypi.org/project/pyarrow/ | YES |
| duckdb | >=0.9.2 | MIT | https://pypi.org/project/duckdb/ | YES |
| apache-airflow | >=2.8.1 | Apache-2.0 | https://pypi.org/project/apache-airflow/ | YES (note: many provider plugins have their own licenses) |
| celery | >=5.3.4 | BSD-3-Clause | https://pypi.org/project/celery/ | YES |
| kombu | >=5.3.4 | BSD-3-Clause | https://pypi.org/project/kombu/ | YES |
| websockets | >=12.0 | BSD-3-Clause | https://pypi.org/project/websockets/ | YES |
| graphene | >=3.3.0 | MIT | https://pypi.org/project/graphene/ | YES |
| strawberry-graphql | >=0.219.0 | MIT | https://pypi.org/project/strawberry-graphql/ | YES |
| python-jose[cryptography] | >=3.3.0 | MIT | https://pypi.org/project/python-jose/ | YES |
| passlib[bcrypt] | >=1.7.4 | BSD-3-Clause | https://pypi.org/project/passlib/ | YES |
| python-multipart | >=0.0.6 | Apache-2.0 | https://pypi.org/project/python-multipart/ | YES |
| authlib | >=1.3.0 | BSD-3-Clause | https://pypi.org/project/Authlib/ | YES |
| keycloak (PyPI package) | >=3.7.0 | Apache-2.0 | https://pypi.org/project/keycloak/ | YES -- VERIFY (note: `python-keycloak` is MIT and is the more common client) |
| opentelemetry-api | >=1.22.0 | Apache-2.0 | https://pypi.org/project/opentelemetry-api/ | YES |
| opentelemetry-sdk | >=1.22.0 | Apache-2.0 | https://pypi.org/project/opentelemetry-sdk/ | YES |
| opentelemetry-instrumentation-fastapi | >=0.43b0 | Apache-2.0 | https://pypi.org/project/opentelemetry-instrumentation-fastapi/ | YES |
| jaeger-client | >=4.8.0 | Apache-2.0 | https://pypi.org/project/jaeger-client/ | YES (deprecated -- migrate to OTel) |
| loguru | >=0.7.2 | MIT | https://pypi.org/project/loguru/ | YES |
| pytest-xdist | >=3.5.0 | MIT | https://pypi.org/project/pytest-xdist/ | YES (dev only) |
| hypothesis | >=6.96.1 | MPL-2.0 | https://pypi.org/project/hypothesis/ | CONDITIONAL -- MPL is file-level; OK if you don't modify hypothesis files. Dev only. |
| factory-boy | >=3.3.0 | MIT | https://pypi.org/project/factory-boy/ | YES (dev only) |
| locust | >=2.20.0 | MIT | https://pypi.org/project/locust/ | YES (dev only) |
| flake8 | >=7.0.0 | MIT | https://pypi.org/project/flake8/ | YES (dev only) |
| bandit | >=1.7.6 | Apache-2.0 | https://pypi.org/project/bandit/ | YES (dev only) |
| safety | >=2.3.5 | MIT | https://pypi.org/project/safety/ | YES (dev only) |
| ruff | >=0.1.9 | MIT | https://pypi.org/project/ruff/ | YES (dev only) |
| ipython | >=8.20.0 | BSD-3-Clause | https://pypi.org/project/ipython/ | YES (dev only) |
| jupyter | >=1.0.0 | BSD-3-Clause | https://pypi.org/project/jupyter/ | YES (dev only) |
| jupyterlab | >=4.0.10 | BSD-3-Clause | https://pypi.org/project/jupyterlab/ | YES (dev only) |
| notebook | >=7.0.6 | BSD-3-Clause | https://pypi.org/project/notebook/ | YES (dev only) |
| ipywidgets | >=8.1.1 | BSD-3-Clause | https://pypi.org/project/ipywidgets/ | YES (dev only) |
| matplotlib | >=3.8.2 | PSF-based / Matplotlib License (BSD-compatible) | https://matplotlib.org/stable/users/project/license.html | YES |
| seaborn | >=0.13.1 | BSD-3-Clause | https://pypi.org/project/seaborn/ | YES |
| plotly | >=5.17.0 | MIT | https://pypi.org/project/plotly/ | YES |
| dash | >=2.16.1 | MIT | https://pypi.org/project/dash/ | YES |
| streamlit | >=1.30.0 | Apache-2.0 | https://pypi.org/project/streamlit/ | YES |
| aiohttp | >=3.9.1 | Apache-2.0 | https://pypi.org/project/aiohttp/ | YES |
| aiofiles | >=23.2.1 | Apache-2.0 | https://pypi.org/project/aiofiles/ | YES |
| aioredis | >=2.0.1 | MIT | https://pypi.org/project/aioredis/ | YES (deprecated; merged into redis-py) |
| dynaconf | >=3.2.4 | MIT | https://pypi.org/project/dynaconf/ | YES |
| hydra-core | >=1.3.2 | MIT | https://pypi.org/project/hydra-core/ | YES |
| omegaconf | >=2.3.0 | BSD-3-Clause | https://pypi.org/project/omegaconf/ | YES |
| click | >=8.1.7 | BSD-3-Clause | https://pypi.org/project/click/ | YES |
| rich | >=13.7.0 | MIT | https://pypi.org/project/rich/ | YES |
| typer | >=0.9.0 | MIT | https://pypi.org/project/typer/ | YES |
| tqdm | >=4.66.1 | MIT + MPL-2.0 (dual) | https://pypi.org/project/tqdm/ | YES |
| python-dateutil | >=2.8.2 | Apache-2.0 / BSD-3-Clause (dual) | https://pypi.org/project/python-dateutil/ | YES |
| pytz | >=2023.4 | MIT | https://pypi.org/project/pytz/ | YES |
| arrow | >=1.3.0 | Apache-2.0 | https://pypi.org/project/arrow/ | YES |
| pendulum | >=3.0.0 | MIT | https://pypi.org/project/pendulum/ | YES |
| marshmallow | >=3.20.2 | MIT | https://pypi.org/project/marshmallow/ | YES |
| cerberus | >=1.3.5 | ISC (approx MIT) | https://pypi.org/project/Cerberus/ | YES |
| jsonschema | >=4.21.1 | MIT | https://pypi.org/project/jsonschema/ | YES |
| pyyaml | >=6.0.1 | MIT | https://pypi.org/project/PyYAML/ | YES |
| toml | >=0.10.2 | MIT | https://pypi.org/project/toml/ | YES |
| requests | >=2.31.0 | Apache-2.0 | https://pypi.org/project/requests/ | YES |
| urllib3 | >=2.1.0 | MIT | https://pypi.org/project/urllib3/ | YES |
| httpcore | >=1.0.2 | BSD-3-Clause | https://pypi.org/project/httpcore/ | YES |
| databases | >=0.8.0 | BSD-3-Clause | https://pypi.org/project/databases/ | YES |
| tortoise-orm | >=0.20.0 | Apache-2.0 | https://pypi.org/project/tortoise-orm/ | YES |
| peewee | >=3.17.0 | MIT | https://pypi.org/project/peewee/ | YES |
| motor | >=3.3.2 | Apache-2.0 | https://pypi.org/project/motor/ | YES |
| pymongo | >=4.6.1 | Apache-2.0 | https://pypi.org/project/pymongo/ | YES (note: MongoDB server is SSPL -- relevant only if you embed/ship the DB) |
| cachetools | >=5.3.2 | MIT | https://pypi.org/project/cachetools/ | YES |
| diskcache | >=5.6.3 | Apache-2.0 | https://pypi.org/project/diskcache/ | YES |
| joblib | >=1.3.2 | BSD-3-Clause | https://pypi.org/project/joblib/ | YES |
| pickle5 | >=0.0.12 | PSF (BSD-style) | https://pypi.org/project/pickle5/ | YES |
| scipy | >=1.12.0 | BSD-3-Clause | https://pypi.org/project/scipy/ | YES |
| statsmodels | >=0.14.1 | BSD-3-Clause | https://pypi.org/project/statsmodels/ | YES |
| arch | >=6.2.0 | NCSA / BSD-style | https://pypi.org/project/arch/ | YES |
| pyfolio | >=0.9.2 | Apache-2.0 | https://pypi.org/project/pyfolio/ | YES |
| empyrical | >=0.5.5 | Apache-2.0 | https://pypi.org/project/empyrical/ | YES |
| zipline-reloaded | >=3.0.3 | Apache-2.0 | https://pypi.org/project/zipline-reloaded/ | YES |
| prophet | >=1.1.5 | MIT | https://pypi.org/project/prophet/ | YES |
| pmdarima | >=2.0.4 | MIT | https://pypi.org/project/pmdarima/ | YES |
| sktime | >=0.25.0 | BSD-3-Clause | https://pypi.org/project/sktime/ | YES |
| tsfresh | >=0.20.2 | MIT | https://pypi.org/project/tsfresh/ | YES |
| bokeh | >=3.3.2 | BSD-3-Clause | https://pypi.org/project/bokeh/ | YES |
| altair | >=5.2.0 | BSD-3-Clause | https://pypi.org/project/altair/ | YES |
| pygal | >=3.0.0 | LGPL-3.0-or-later | https://pypi.org/project/pygal/ | CONDITIONAL (LGPL, dynamic-link OK) |
| wordcloud | >=1.9.2 | MIT | https://pypi.org/project/wordcloud/ | YES |
| pillow | >=10.2.0 | MIT-CMU (HPND) | https://pypi.org/project/pillow/ | YES |
| line-profiler | >=4.1.1 | BSD-3-Clause | https://pypi.org/project/line-profiler/ | YES (dev only) |
| memory-profiler | >=0.61.0 | BSD-3-Clause | https://pypi.org/project/memory-profiler/ | YES (dev only) |
| py-spy | >=0.3.14 | MIT | https://pypi.org/project/py-spy/ | YES (dev only) |
| memray | >=1.10.0 | Apache-2.0 | https://pypi.org/project/memray/ | YES (dev only) |
| scalene | >=1.5.26 | Apache-2.0 | https://pypi.org/project/scalene/ | YES (dev only) |
| gunicorn | >=21.2.0 | MIT | https://pypi.org/project/gunicorn/ | YES |
| docker (Python SDK) | >=7.0.0 | Apache-2.0 | https://pypi.org/project/docker/ | YES |
| kubernetes (Python client) | >=28.1.0 | Apache-2.0 | https://pypi.org/project/kubernetes/ | YES |
| boto3 | >=1.34.34 | Apache-2.0 | https://pypi.org/project/boto3/ | YES |
| google-cloud-storage | >=2.10.0 | Apache-2.0 | https://pypi.org/project/google-cloud-storage/ | YES |
| azure-storage-blob | >=12.19.0 | MIT | https://pypi.org/project/azure-storage-blob/ | YES |
| minio | >=7.2.3 | Apache-2.0 | https://pypi.org/project/minio/ | YES |
| asyncio (stdlib backport) | >=3.4.3 | PSF | https://pypi.org/project/asyncio/ | YES |

### 2c. `services/market-data/requirements.txt`

| Package | Version | License | Safe? |
|---|---|---|---|
| yfinance | (latest) | Apache-2.0 | YES (Yahoo ToS caveat) |
| pandas | (latest) | BSD-3-Clause | YES |
| numpy | (latest) | BSD-3-Clause | YES |
| pytest | (latest) | MIT | YES (dev) |
| pytest-asyncio | (latest) | Apache-2.0 | YES (dev) |

### 2d. `services/backtesting-engine/requirements.txt`

| Package | Version | License | Safe? |
|---|---|---|---|
| **nautilus_trader** | (latest) | **LGPL-3.0-or-later** | CONDITIONAL |
| vectorbt | (latest) | Apache-2.0 | YES |
| pandas | (latest) | BSD-3-Clause | YES |
| numpy | (latest) | BSD-3-Clause | YES |
| TA-Lib | (latest) | BSD-2-Clause | YES |
| clickhouse-connect | (latest) | Apache-2.0 | YES |
| kafka-python | (latest) | Apache-2.0 | YES |

### 2e. `services/trading-engine/requirements.txt`

| Package | Version | License | Safe? |
|---|---|---|---|
| **nautilus_trader** | (latest) | **LGPL-3.0-or-later** | CONDITIONAL |
| ib_insync | (latest) | BSD-2-Clause | YES |
| kafka-python | (latest) | Apache-2.0 | YES |
| pandas | (latest) | BSD-3-Clause | YES |
| numpy | (latest) | BSD-3-Clause | YES |
| pydantic | (latest) | MIT | YES |
| loguru | (latest) | MIT | YES |
| scipy | (latest) | BSD-3-Clause | YES |

### 2f. `services/ai-assistant/requirements.txt`

| Package | Version | License | Safe? |
|---|---|---|---|
| openai | >=1.30.0 | Apache-2.0 | YES |
| langchain | >=0.3.0 | MIT | YES |
| langchain-openai | >=0.2.0 | MIT | YES |
| langgraph | >=0.2.0 | MIT | YES |
| qdrant-client | >=1.9.0 | Apache-2.0 | YES |
| sentence-transformers | >=3.0.0 | Apache-2.0 | YES (model weights may have separate licenses -- verify any model you ship) |
| pydantic | >=2.0 | MIT | YES |
| pydantic-settings | >=2.0 | MIT | YES |
| numpy | >=1.24.0 | BSD-3-Clause | YES |
| confluent-kafka | >=2.3.0 | Apache-2.0 | YES |
| structlog | >=24.0.0 | Apache-2.0 / MIT | YES |
| python-json-logger | >=2.0.0 | BSD-2-Clause | YES |
| asyncpg | >=0.29.0 | Apache-2.0 | YES |
| python-dotenv | >=1.0.0 | BSD-3-Clause | YES |

### 2g. `libs/quant/pyproject.toml`

| Package | License | Safe? |
|---|---|---|
| numpy | BSD-3-Clause | YES |
| pandas | BSD-3-Clause | YES |
| TA-Lib | BSD-2-Clause | YES |

### 2h. `libs/core/pyproject.toml`

| Package | License | Safe? |
|---|---|---|
| pydantic | MIT | YES |
| kafka-python | Apache-2.0 | YES |

### 2i. Frontend / dashboard JavaScript

No `package.json` was found in the audited tree (`services/dashboard/` currently contains only a Python `src/api.py`). The mention of Next.js / TradingView Lightweight Charts in the audit brief is **not yet materialised in code**. If/when added:

| Package | License | Safe? |
|---|---|---|
| Next.js (anticipated) | MIT | YES |
| React | MIT | YES |
| TradingView Lightweight Charts | Apache-2.0 (with TradingView attribution requirement) | YES -- must keep TradingView attribution in the chart UI |

---

## 3. High-Risk Dependencies (Detailed)

### 3.1 nautilus-trader -- LGPL-3.0-or-later  [CONDITIONAL]
**Used in:** `services/trading-engine/`, `services/backtesting-engine/`, and integration code under `core_trading/strategies/` (NautilusTrader integration adapters).

**Risk:** LGPL is weak copyleft. In Python, `import nautilus_trader` is treated as **dynamic linking**, which the LGPL allows for closed-source consumers. To stay compliant:

1. Do not modify Nautilus source files. If you must, those modifications must be published under LGPL.
2. Ship `nautilus-trader` as an installable dependency (e.g., via `pip install`), not bundled/static-compiled into your binary.
3. Include the LGPL-3.0 license text and an attribution notice in your product's THIRD_PARTY_NOTICES.
4. Users must be able to substitute a different/modified `nautilus-trader` for the one you ship -- `pip install nautilus-trader==X.Y` satisfies this naturally.

**Bottom line:** Safe for closed-source MAS provided you treat it as an external dependency and do not fork/embed it.

### 3.2 psycopg2-binary -- LGPL-3.0+ (with OpenSSL exception)  [CONDITIONAL]
Same LGPL-dynamic-linking analysis as Nautilus. Python import = dynamic. Safe for closed-source as a `pip` dependency. Alternative: **`psycopg[binary]` (psycopg3) is also LGPL**, so swapping doesn't help. `asyncpg` (Apache-2.0) is a fully permissive alternative for async workloads.

### 3.3 pygal -- LGPL-3.0+  [CONDITIONAL]
Only used (if at all) as a charting library. Dynamic-link safe. Easy to swap to `matplotlib` / `plotly` / `bokeh` (all permissive) if you want zero copyleft risk.

### 3.4 pylint -- GPL-2.0  [DEV-ONLY, OK]
Used only as a developer linter. Not shipped, not imported by runtime code. **Safe.**

### 3.5 hypothesis -- MPL-2.0  [CONDITIONAL, DEV-ONLY]
Used for property-based testing. MPL is file-level copyleft. As long as you do not modify hypothesis source files, no contamination. **Safe in dev/test only.**

### 3.6 Neo4j (server, Docker image `neo4j:5.25-community`) -- GPL-3.0  [CONDITIONAL]
**This is the biggest server-side licensing concern.**

- Neo4j **Community Edition** is licensed under **GPL-3.0**.
- Neo4j **Enterprise Edition** is commercial-licensed.

**The good news (Network Service exception):** GPL is triggered only by *distribution*. If your MAS connects to a Neo4j server **over Bolt/HTTP** and you do not ship the Neo4j binary as part of your product, you are NOT creating a derivative work. The Python client `neo4j` (Apache-2.0) is fine.

**The bad news (Distribution):** If your MAS is sold as an on-premise appliance, a Docker bundle, an installer that bundles Neo4j Community, an embedded Neo4j JAR, or any redistributable artifact that contains the Neo4j Community binary -- that distribution must be GPL-3.0, contaminating your entire product.

**Mitigations:**
- (a) Require customers to install Neo4j themselves (no distribution by you).
- (b) Buy a **Neo4j Enterprise commercial license** (allows OEM/embedded distribution).
- (c) Replace Neo4j Community with **Memgraph Community (BSL -> eventually Apache-2.0)**, **ArangoDB Community (Apache-2.0)**, or **Apache AGE on Postgres (Apache-2.0)**.

### 3.7 Redis (Docker image `redis:7.4-alpine`) -- SSPL / RSALv2 dual  [CONDITIONAL]
Redis 7.4+ moved to **SSPL-1.0 + RSALv2 dual license** (away from BSD-3). This is **source-available**, NOT open-source by OSI definition.

**Practical implications for MAS:**
- **OK:** Embedding Redis inside your product, running it on infrastructure you control, selling a product that *uses* Redis internally.
- **NOT OK under RSALv2:** Offering Redis itself as a managed/hosted DBaaS to third parties (i.e., competing with Redis Inc.).
- **NOT OK under SSPL (without releasing your source under SSPL):** Offering "Redis as a service."

For a closed-source algorithmic-trading product that uses Redis as a cache/queue, **you are fine**.

**If concerned:** Pin to **Redis 7.2.x** (still BSD-3-Clause), or switch to **Valkey** (the Linux Foundation BSD-licensed fork of Redis 7.2), or **KeyDB** (BSD).

### 3.8 confluent-kafka (Python) -- Apache-2.0  [OK]
The Python client wraps librdkafka (BSD-2-Clause). Both are permissive. Safe.

### 3.9 langgraph -- MIT  [OK]
Open-core: the OSS package itself is MIT. The **LangGraph Platform / LangGraph Cloud / LangSmith** hosted offerings are commercial -- if you adopt those services you need a paid subscription, but that doesn't affect MIT licensing of the OSS library.

### 3.10 vectorbt -- Apache-2.0  [OK]
Free edition is Apache-2.0. **vectorbt PRO** is closed-source and commercial. Confirm the code only uses the OSS edition (the `vectorbt` PyPI package).

### 3.11 QuantLib -- Modified BSD  [OK]
Permissive. Free for commercial use. Safe.

### 3.12 TA-Lib -- BSD-2-Clause  [OK]
Both the C library and the Python wrapper are BSD-2-Clause. Safe.

### 3.13 FinRL -- MIT  [OK]
*Note: FinRL is mentioned in the audit brief under `services/ml-strategy/` but no such service directory currently exists in the repo (only `ai-assistant`, `backtesting-engine`, `compliance`, `dashboard`, `market-data`, `notifications`, `risk-manager`, `trading-engine`). If/when FinRL is added, it is MIT-licensed.* **Safe.**

### 3.14 ib-insync -- BSD-2-Clause  [OK]
Safe. Note that the IBKR TWS API itself (Java/C++) has its own [IBKR API license](https://www.interactivebrokers.com/en/index.php?f=5041) which prohibits redistribution of the TWS API binaries without permission. ib_insync wraps that API; ib_insync itself is BSD, but if you ship the IBKR API binaries with your product, IBKR's terms apply -- typically users install TWS themselves.

### 3.15 Docker image: PostgreSQL (`pgvector/pgvector:pg17`)  [OK]
Postgres is under the **PostgreSQL License** (MIT-style). pgvector extension is **PostgreSQL License**. Safe.

### 3.16 Docker image: ClickHouse (`clickhouse/clickhouse-server:24.8`)  [OK]
**Apache-2.0.** Safe for any commercial use including DBaaS.

### 3.17 Docker image: Keycloak (`quay.io/keycloak/keycloak:26.0`)  [OK]
**Apache-2.0.** Safe.

### 3.18 Docker image: Kafka (`confluentinc/cp-kafka:7.7.0`) and Schema Registry  [CONDITIONAL]
- Apache Kafka itself: **Apache-2.0**. Safe.
- **Confluent Platform images (`cp-kafka`, `cp-schema-registry`)** are subject to the **Confluent Community License v1.0** for components like Schema Registry, KSQL, REST Proxy, and Confluent Hub. This license **prohibits offering the software as a competing SaaS** (similar to BSL). For internal use or embedding in your product (non-competing with Confluent), this is fine.
- If you want pure Apache-2.0 alternatives: use the upstream `apache/kafka` image and `apicurio/apicurio-registry` (Apache-2.0) instead of Confluent Schema Registry.

### 3.19 Docker image: Qdrant (`qdrant/qdrant:v1.12.0`)  [OK]
**Apache-2.0.** Safe.

### 3.20 Docker image: Grafana (`grafana/grafana:10.2.3`)  [CONDITIONAL]
Grafana switched to **AGPL-3.0** as of v10.x (April 2024). **AGPL applies only to derivative works of Grafana**, NOT to applications that merely send metrics to Grafana or embed Grafana dashboards via iframe / URL. Running Grafana as a separate, unmodified service alongside your product does **not** contaminate your product.

**Caveats:**
- Do not fork or modify Grafana source and ship it.
- Do not bundle the Grafana binary inside your product distribution. Have customers run Grafana themselves, or buy **Grafana Enterprise** for commercial OEM distribution.
- Embedding Grafana dashboards via `<iframe>` or links from your product is fine.

### 3.21 Docker image: Loki / Promtail (`grafana/loki:2.9.3`, `grafana/promtail:2.9.3`)  [OK]
**Apache-2.0** at v2.9. (Loki 3.x and later are AGPL-3.0 -- same caveats as Grafana would apply if you upgrade.)

### 3.22 Docker image: Prometheus (`prom/prometheus:v2.48.1`)  [OK]
**Apache-2.0.** Safe.

### 3.23 Docker image: kafka-ui (`provectuslabs/kafka-ui`)  [CONDITIONAL -- VERIFY]
Provectus Kafka UI is **Apache-2.0** through ~v0.7, and the project was renamed to **Kafbat UI** with continued Apache-2.0 licensing. Safe to use as a separate operational service. Not part of distributable product code.

---

## 4. Feature -> License Map

The "Effective License" column = the **most restrictive transitive license** in the feature's dependency tree.

| Feature Directory | Direct Deps of Note | Effective License | Notes |
|---|---|---|---|
| `core_trading/adapters/` (IBKR adapter, multi-broker) | `ib_insync` (BSD-2), `asyncio`, `pydantic` | BSD-2-Clause | Plus IBKR TWS API ToS for TWS itself (do not redistribute) |
| `core_trading/strategies/` (all strategies) | `pandas`, `numpy`, `scipy`, `ta`, `ta-lib`, `scikit-learn` | BSD-3-Clause | All permissive |
| `core_trading/engines/execution_engine.py`, `risk_engine.py` | pandas, numpy, internal libs | BSD-3-Clause | |
| `core_trading/engines/smart_money_engine/` | pandas, numpy | BSD-3-Clause | |
| `core_trading/engines/multi_timeframe_engine/` | pandas, numpy | BSD-3-Clause | |
| `core_trading/engines/ai_enhanced_signal_engine.py` | langchain, openai, anthropic | Apache-2.0 (from openai) | All permissive overall |
| `core_trading/engines/parallel_processing_engine.py` | celery, kombu, joblib | BSD-3-Clause | |
| `core_trading/engines/portfolio_engine.py` | pyportfolioopt, riskfolio-lib | BSD-3-Clause | |
| `core_trading/engines/strategy_engine.py` + integration with Nautilus | nautilus-trader (LGPL-3.0) | **LGPL-3.0** | Dynamic-link safe |
| `services/trading-engine/` (NautilusTrader live trading) | nautilus-trader, ib_insync | **LGPL-3.0** | Dynamic-link safe; biggest LGPL exposure point |
| `services/backtesting-engine/` (VectorBT + Nautilus) | nautilus-trader, vectorbt, ta-lib | **LGPL-3.0** | Same as above |
| `services/ai-assistant/` (LangGraph) | langgraph, langchain, openai, qdrant-client, sentence-transformers | Apache-2.0 | All permissive; verify any HuggingFace model weights you embed |
| `services/fundamental-analysis/` | *(directory not present in repo -- referenced in audit brief but absent)* | n/a | Section is aspirational; see Action Items |
| `services/options-service/` (QuantLib) | *(directory not present -- only `quantlib` referenced in root requirements.txt)* | BSD-3-Clause | When added: QuantLib is modified-BSD, safe |
| `services/ml-strategy/` (FinRL, PyTorch) | *(directory not present in repo)* | BSD-3-Clause (PyTorch) | When added: FinRL=MIT, PyTorch=BSD-3, both safe |
| `services/market-data/` | yfinance, pandas, numpy | Apache-2.0 | Yahoo Finance **ToS forbids commercial scraping** -- switch to paid data provider for MAS |
| `services/risk-manager/` | pydantic, kafka-python (only stdlib otherwise) | MIT | Safe |
| `services/compliance/` | (inspection: `src/` is minimal stub) | n/a | Likely permissive when fleshed out |
| `services/notifications/` | (inspection: `src/` is minimal stub) | n/a | Likely permissive |
| `services/dashboard/` (Python backend) + future frontend | fastapi (MIT). Future: Next.js (MIT) + TradingView Lightweight Charts (Apache-2.0) | Apache-2.0 (when frontend added) | Must keep TradingView attribution in chart UI |
| `libs/common/` | (inspection: helpers, no third-party deps detected) | MIT-equivalent (your own code) | Safe |
| `libs/core/` | pydantic, kafka-python | Apache-2.0 / MIT | Safe |
| `libs/database/` | sqlalchemy, asyncpg, psycopg2-binary, clickhouse-driver, neo4j (driver), redis | **LGPL-3.0** (due to `psycopg2-binary`) | Dynamic-link safe; or swap to `asyncpg` only for fully-permissive |
| `libs/messaging/` | kafka-python, confluent-kafka, avro | Apache-2.0 | Safe |
| `libs/fundamental/` | (verify imports) | VERIFY | Likely pandas/numpy/requests stack -- permissive |
| `libs/quant/` | numpy, pandas, TA-Lib | BSD-3-Clause | Safe |
| `libs/testing/` | pytest, faker, hypothesis | MPL-2.0 (hypothesis) | Dev-only; safe |
| `infrastructure/postgres/` | PostgreSQL 17 + pgvector | PostgreSQL License | Safe -- redistribute freely |
| `infrastructure/clickhouse/` | ClickHouse 24.8 | Apache-2.0 | Safe |
| `infrastructure/neo4j/` | Neo4j 5.25 Community | **GPL-3.0** | Do NOT redistribute the binary. Run as separate service or buy Enterprise. |
| `infrastructure/kafka/` | Confluent Platform 7.7 (Kafka + Schema Registry) | Apache-2.0 (Kafka) + Confluent Community License (Schema Registry) | OK for internal; switch to `apache/kafka` + `apicurio` if you redistribute |
| `infrastructure/grafana/` | Grafana 10.2.3 | **AGPL-3.0** | Do NOT bundle in your distribution. Run separately. |
| `infrastructure/loki/`, `infrastructure/promtail/` | Loki 2.9.3 | Apache-2.0 | Safe at this version. AGPL if you upgrade to 3.x. |
| `infrastructure/prometheus/` | Prometheus 2.48 | Apache-2.0 | Safe |
| Redis (image `redis:7.4-alpine`) | Redis 7.4 | **SSPL + RSALv2 dual** | OK for internal/embedded use; NOT OK if you sell Redis-as-a-Service |
| Qdrant (image `qdrant/qdrant:v1.12.0`) | Qdrant | Apache-2.0 | Safe |
| Keycloak (image `quay.io/keycloak/keycloak:26.0`) | Keycloak | Apache-2.0 | Safe |

---

## 5. MAS-Merge Recommendations

For each feature, a one-line verdict on lifting it into the closed-source Multi-Agent System.

| Feature | Verdict |
|---|---|
| `core_trading/adapters/` (IBKR + multi-broker) | **Safe to merge** into closed-source MAS. Retain ib_insync BSD attribution. Do not bundle IBKR TWS binaries. |
| `core_trading/strategies/` (all pure-Python strategies) | **Safe to merge.** All transitive deps are permissive (pandas/numpy/scipy/ta-lib BSD/MIT). |
| `core_trading/engines/` (execution, backtesting, risk, smart-money) | **Safe to merge**, EXCEPT the Nautilus-integration adapters (`integration.py`, `nautilus_integration_example.py`, `pipeline_integration.py`). Those tie you to LGPL -- see below. |
| `services/trading-engine/` (NautilusTrader live) | **Can merge with conditions:** install nautilus-trader via pip (dynamic link), do not modify nautilus source, include LGPL-3.0 NOTICE in your distribution. |
| `services/backtesting-engine/` (VectorBT + Nautilus) | **Can merge with conditions:** same LGPL conditions as trading-engine. VectorBT itself is Apache-2.0 and unconditional. |
| `services/ai-assistant/` (LangGraph) | **Safe to merge.** LangGraph OSS is MIT. If you adopt LangGraph Platform (hosted), that's a separate paid commercial relationship. |
| `services/fundamental-analysis/` | **Aspirational** -- directory not present in repo. Likely safe when added (pandas/numpy/requests stack). |
| `services/options-service/` (QuantLib) | **Safe to merge.** QuantLib is modified-BSD. Retain attribution. |
| `services/ml-strategy/` (FinRL + PyTorch) | **Aspirational** -- directory not present. When added: safe (MIT + BSD-3). Verify any pretrained model weights' licenses separately. |
| `services/market-data/` | **Safe to merge in code**, but **swap `yfinance` data source** -- Yahoo Finance ToS forbids commercial scraping. Use a paid provider (IEX Cloud, Polygon.io, Tiingo, Alpha Vantage, Finnhub paid tier). |
| `services/risk-manager/` | **Safe to merge.** Pure permissive stack. |
| `services/compliance/`, `services/notifications/` | **Safe to merge** based on current minimal stubs; re-audit when fleshed out. |
| `services/dashboard/` + future frontend | **Safe to merge.** Next.js MIT, React MIT, TradingView Lightweight Charts Apache-2.0 -- keep the required TradingView attribution visible in the chart UI. |
| `libs/common/`, `libs/core/`, `libs/messaging/`, `libs/quant/` | **Safe to merge.** Permissive. |
| `libs/database/` | **Safe to merge with conditions:** `psycopg2-binary` is LGPL -- install via pip, do not bundle/modify. Cleanest fix: use `asyncpg` (Apache-2.0) exclusively. |
| `libs/testing/` | **Safe to merge (dev-only).** hypothesis MPL only matters if you modify hypothesis itself. |
| `infrastructure/postgres/` (PostgreSQL + pgvector) | **Safe to redistribute** if you ever ship containers. |
| `infrastructure/clickhouse/` | **Safe to redistribute.** Apache-2.0. |
| `infrastructure/neo4j/` (Community Edition) | **Cannot redistribute the binary** (GPL-3.0). Options: (a) require customers to install Neo4j themselves, (b) buy Neo4j Enterprise OEM license, (c) replace with Memgraph / ArangoDB / Apache AGE. |
| `infrastructure/kafka/` (Confluent Platform) | **Can merge for internal use.** For redistribution, replace `confluentinc/cp-kafka` + `cp-schema-registry` with `apache/kafka` + `apicurio/apicurio-registry` to drop the Confluent Community License. |
| `infrastructure/redis` (Redis 7.4) | **Can merge** for internal/embedded use under SSPL/RSALv2. **Cannot resell** Redis-as-a-Service. If concerned, pin Redis 7.2.x or switch to Valkey / KeyDB (BSD). |
| `infrastructure/grafana/` (10.x) | **Can merge with conditions:** do NOT bundle Grafana in your distributable. Run it as a separate service customers connect to, or buy Grafana Enterprise. Embedding via iframe/URL is fine. |
| `infrastructure/loki/` (2.9.x) | **Safe to redistribute** at v2.9 (Apache-2.0). Re-audit if upgrading to Loki 3.x (AGPL). |
| `infrastructure/prometheus/`, `infrastructure/promtail/` | **Safe to redistribute.** Apache-2.0. |
| `infrastructure/keycloak/` | **Safe to redistribute.** Apache-2.0. |
| `infrastructure/qdrant/` | **Safe to redistribute.** Apache-2.0. |

---

## 6. Action Items

Concrete remediations, ordered by priority, for cleanly lifting features into a commercialized MAS.

### Priority 1 -- Avoid GPL/AGPL Contamination in Redistributable Bundles

1. **If MAS is sold as an on-premise appliance / installer / Docker bundle:**
   - **Replace Neo4j Community (GPL-3.0)** with one of:
     - **Apache AGE** (PostgreSQL extension, Apache-2.0) -- easiest swap since you already run Postgres.
     - **Memgraph Community** (BSL-1.1 -> Apache-2.0 after 4 years) -- Cypher-compatible.
     - **ArangoDB Community** (Apache-2.0) -- multi-model.
     - Or buy a **Neo4j Enterprise OEM license** (commercial).
   - **Do not bundle Grafana 10.x (AGPL-3.0)** in the distribution. Either (a) require customer-installed Grafana, (b) buy Grafana Enterprise, or (c) replace with a permissive dashboarding stack (e.g., Apache Superset = Apache-2.0).

2. **If MAS is sold purely as a hosted SaaS where customers never receive the binaries:**
   - Neo4j Community and Grafana 10.x are both fine to *run* (network-service usage doesn't trigger GPL/AGPL distribution clauses), but be aware AGPL Section 13 still requires you to **offer Grafana source code to your end users** if your modifications change Grafana. Solution: don't modify Grafana -- only configure/theme it.

### Priority 2 -- LGPL Dependencies (Lower Risk, Easy Wins)

3. **NautilusTrader (LGPL-3.0):** Keep as a pip-installed dependency, never fork. Add to your `THIRD_PARTY_NOTICES.txt`:
   ```
   This product uses NautilusTrader (https://nautilustrader.io/) under the
   GNU Lesser General Public License v3.0. Source available at
   https://github.com/nautechsystems/nautilus_trader. A copy of the LGPL-3.0
   license is included.
   ```
4. **psycopg2-binary (LGPL-3.0+):** Same NOTICE treatment. Or migrate fully to `asyncpg` (Apache-2.0) for the async paths and drop psycopg2 entirely if no sync ORM code depends on it.
5. **pygal (LGPL-3.0+):** If only used for charts, swap to `plotly` or `matplotlib` (both permissive). Otherwise treat like NautilusTrader.

### Priority 3 -- Source-Available Database Licensing

6. **Redis 7.4 (SSPL + RSALv2):** Acceptable for internal/embedded use. If you ever consider selling a managed-Redis offering, **stop and review with legal.** Alternatively, pin Redis 7.2.x (still BSD-3) or migrate to **Valkey** (Linux Foundation fork, BSD-3) or **KeyDB**.

7. **Confluent Platform (Community License):** Replace with upstream Apache Kafka images for any redistributed appliance: `apache/kafka:3.x` and `apicurio/apicurio-registry-mem` (Apache-2.0 Schema Registry).

### Priority 4 -- Data-Source Terms of Service (Not Licensing per se, but Commercially Critical)

8. **`yfinance`** is Apache-2.0 software, but Yahoo Finance's data ToS prohibits use in commercial / for-profit applications. Replace with a paid commercial-data subscription before shipping MAS:
   - IEX Cloud / Polygon.io / Tiingo / Alpha Vantage Premium / Finnhub Premium for equities
   - Refinitiv / Bloomberg / FactSet for institutional
9. **IBKR TWS API** binaries are subject to IBKR's API license. Have customers install TWS / IB Gateway themselves; ship only your `ib_insync`-based code.
10. **OpenAI / Anthropic / LangChain providers:** All Python clients are permissive (Apache-2.0 / MIT), but the API services have their own commercial ToS -- review for any MAS resale model.

### Priority 5 -- Attribution Hygiene

11. Add a `THIRD_PARTY_NOTICES.md` to the MAS distribution that lists every Apache-2.0 NOTICE file content (xgboost, openai, tenacity, prometheus, etc.) and every BSD/MIT copyright header.
12. For the future Next.js dashboard with TradingView Lightweight Charts: per their license, the **TradingView attribution must remain visible in the chart UI** (small "TradingView" link in the watermark). Do not remove it.
13. If you ship any HuggingFace model weights via `sentence-transformers`, audit each model's individual license (Apache-2.0, MIT, OpenRAIL, Llama Community License, etc.) -- these are independent of `sentence-transformers` itself.

### Priority 6 -- Repository Hygiene Cleanup (Not Licensing, But Spotted During Audit)

14. The audit brief references `services/fundamental-analysis/`, `services/options-service/`, `services/ml-strategy/`, and `frontend/` -- none of these exist in the current tree. Either add them or update internal docs to reflect actual scope (`ai-assistant`, `backtesting-engine`, `compliance`, `dashboard`, `market-data`, `notifications`, `risk-manager`, `trading-engine`).
15. Many files in `core_trading/strategies/` and `core_trading/adapters/` have `.fixed_attempt`, `.backup`, `.archived` siblings. Clean these up before code review / packaging -- they could leak into MAS by accident and complicate IP/license accounting.

---

## Disclaimer

This audit is informational and reflects publicly documented license metadata at the time of writing. It is **not legal advice**. Before shipping a commercial product, have a software-licensing attorney review the final dependency manifest, especially the LGPL (NautilusTrader, psycopg2, pygal), GPL (Neo4j Community), AGPL (Grafana 10.x), and source-available (Redis 7.4, Confluent Community License) components. License terms upstream can change between versions -- re-audit at every major dependency upgrade.
