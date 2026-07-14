# API Schema Documentation

## OpenAPI Specs for RNR-IBKR-Algo-Trader Microservices

This directory contains OpenAPI specifications for the 28 microservices.

---

## Swagger UI Endpoints

Once deployed, access the Swagger UI at:
- **Local**: http://localhost:8080/api/docs
- **Development**: https://dev-api.trading-system.com/api/docs
- **Production**: https://api.trading-system.com/api/docs

---

## Microservices API Specifications

### Trading Engine API
- OpenAPI Spec: `trading_engine_openapi.yaml`
- Base Path: `/api/v1/trading`
- Endpoints:
  - `POST /orders` - Submit new order
  - `GET /orders/{order_id}` - Get order details
  - `GET /orders?user_id={id}` - List user orders
  - `DELETE /orders/{order_id}` - Cancel order
  - `GET /positions` - Get current positions
  - `POST /signals` - Submit trading signal

### Market Data API
- OpenAPI Spec: `market_data_openapi.yaml`
- Base Path: `/api/v1/market`
- Endpoints:
  - `GET /quotes/{symbol}` - Get real-time quote
  - `GET /history/{symbol}?period={d}` - Get historical data
  - `GET /book/{symbol}` - Get order book
  - `POST /subscribe` - Subscribe to real-time data

### Risk Manager API
- OpenAPI Spec: `risk_manager_openapi.yaml`
- Base Path: `/api/v1/risk`
- Endpoints:
  - `GET /limits` - Get user risk limits
  - `POST /check` - Pre-trade risk check
  - `GET /exposure` - Get current exposure
  - `GET /metrics` - Get risk metrics

### Backtesting Engine API
- OpenAPI Spec: `backtesting_openapi.yaml`
- Base Path: `/api/v1/backtest`
- Endpoints:
  - `POST /run` - Run backtest
  - `GET /results/{run_id}` - Get backtest results
  - `GET /metrics` - Get performance metrics

### AI Assistant API
- OpenAPI Spec: `ai_assistant_openapi.yaml`
- Base Path: `/api/v1/ai`
- Endpoints:
  - `POST /query` - Submit natural language query
  - `GET /suggestions/{symbol}` - Get AI trading suggestions
  - `POST /analyze` - Analyze strategy with AI

### Fundamental Analysis API
- OpenAPI Spec: `fundamental_analysis_openapi.yaml`
- Base Path: `/api/v1/fundamental`
- Endpoints:
  - `GET /ratios/{symbol}` - Get financial ratios
  - `GET /valuations/{symbol}` - Get valuation models
  - `GET /scores/{symbol}` - Get quality scores
  - `GET /earnings/{symbol}` - Get earnings data

### Portfolio Manager API
- OpenAPI Spec: `portfolio_manager_openapi.yaml`
- Base Path: `/api/v1/portfolio`
- Endpoints:
  - `GET /summary/{user_id}` - Get portfolio summary
  - `POST /rebalance` - Trigger portfolio rebalance
  - `GET /performance/{user_id}` - Get performance metrics

---

## Common API Patterns

### Authentication
All API endpoints use JWT token authentication:

```http
Authorization: Bearer <jwt_token>
```

### Response Format
All API responses follow this format:

```json
{
  "success": true,
  "data": { ... },
  "message": "Operation successful",
  "trace_id": "uuid-for-distributed-tracing"
}
```

### Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": { ... }
  },
  "trace_id": "uuid-for-distributed-tracing"
}
```

### Pagination
List endpoints use cursor-based pagination:

```http
GET /api/v1/trading/orders?user_id=123&cursor=abc123&limit=50
```

---

## Rate Limiting

| Tier | Requests/Minute | Burst |
|-------|----------------|--------|
| Free | 60 | 10 |
| Pro | 600 | 50 |
| Enterprise | 6000 | 200 |

---

## API Versioning

- **Current Version**: v1
- **Base Path**: `/api/v1/`
- **Version Header**: `API-Version: 1.0.0`

---

## Security

### CORS
Allowed origins:
- `http://localhost:3000` (development)
- `https://trading-system.com` (production)

### Security Headers
All responses include:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

---

## Webhooks

### Supported Events

- `order.filled` - Order execution notification
- `position.opened` - New position notification
- `triggered_signal` - Trading signal triggered
- `risk_alert` - Risk limit breach
- `backtest_complete` - Backtest finished

### Webhook Format

```http
POST /webhook-url
Content-Type: application/json

{
  "event": "order.filled",
  "data": { ... },
  "timestamp": "2025-02-03T12:00:00Z",
  "signature": "hmac_signature"
}
```

---

## OpenAPI Specification Example

```yaml
openapi: 3.0.0
info:
  title: IBKR Trading Engine API
  version: 1.0.0
  description: Trading engine for IBKR algorithmic trading system
  contact:
    name: API Support
    email: support@trading-system.com

servers:
  - url: http://localhost:8080/api/v1/trading
    description: Local development
  - url: https://api.trading-system.com/api/v1/trading
    description: Production

paths:
  /orders:
    post:
      summary: Create new order
      operationId: createOrder
      tags:
        - Orders
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/OrderRequest'
      responses:
        '200':
          description: Order created successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderResponse'
        '400':
          description: Bad request
        '401':
          description: Unauthorized

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    OrderRequest:
      type: object
      required:
        - symbol
        - side
        - quantity
      properties:
        symbol:
          type: string
          example: "AAPL"
        side:
          type: string
          enum: [BUY, SELL]
          example: "BUY"
        quantity:
          type: number
          minimum: 1
          example: 100
        order_type:
          type: string
          enum: [MARKET, LIMIT, STOP]
          default: "LIMIT"
        price:
          type: number
          description: Required only for LIMIT orders

    OrderResponse:
      type: object
      properties:
        success:
          type: boolean
          example: true
        data:
          $ref: '#/components/schemas/Order'
        message:
          type: string
          example: "Order created successfully"
        trace_id:
          type: string
          format: uuid
```

---

## API Keys

To generate API keys:
1. Log into the trading dashboard
2. Navigate to Settings > API Keys
3. Create new key with appropriate permissions
4. Store the key securely (never commit to code)

---

## Generating OpenAPI Specs

To generate OpenAPI specs from FastAPI applications:

```bash
# From trading-engine service
cd services/trading-engine
poetry run python -m openapi trading_engine.main > docs/api/trading_engine_openapi.yaml

# Generate HTML docs
poetry run python -m openapi trading_engine.main --output docs/api/trading_engine.html
```

---

## API Documentation Tools

- **Swagger UI**: `/api/docs` - Interactive API documentation
- **Redoc**: `/api/redoc` - Alternative documentation viewer
- **JSON Schema**: `/api/openapi.json` - Machine-readable spec
- **YAML Spec**: `/api/openapi.yaml` - Editable OpenAPI spec

---

## Testing APIs

```bash
# Install API testing tools
pip install httpie pytest-httpbin

# Test API endpoint
http GET https://api.trading-system.com/api/v1/trading/orders \
  Authorization:"Bearer <jwt_token>"

# Run API integration tests
cd tests/integration/api/
poetry run pytest api_test_suite.py
```

---

For detailed API documentation for each service, see the individual OpenAPI YAML files in this directory.
