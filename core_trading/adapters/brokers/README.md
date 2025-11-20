# Broker Adapters Documentation

This directory contains comprehensive broker adapter implementations for the NautilusTrader engine, providing seamless integration with multiple financial service providers across various asset classes.

## Overview

The broker adapter system is designed with enterprise-grade features including:
- **Unified Interface**: Consistent API across all broker implementations
- **Comprehensive Error Handling**: Robust error management and recovery
- **Security & Authentication**: Enterprise-grade security protocols
- **Rate Limiting**: Intelligent request throttling and connection management
- **Real-time Streaming**: WebSocket support for live market data
- **Health Monitoring**: Continuous monitoring and alerting system
- **Configuration Validation**: Comprehensive validation and error reporting

## Supported Brokers

### Primary Brokers

#### Interactive Brokers (IBKR)
- **File**: `interactive_brokers.py`
- **Asset Classes**: Stocks, ETFs, Options, Futures, Forex, CFDs
- **Features**:
  - Paper and live trading support
  - Advanced order types (Market, Limit, Stop, Bracket, etc.)
  - Real-time market data streaming
  - Portfolio management and reporting
  - Multi-currency support
- **Authentication**: API key and secret with optional 2FA
- **Rate Limits**: 50 requests/second (configurable)
- **Status**: ✅ Production Ready

#### Alpaca
- **File**: `alpaca.py`
- **Asset Classes**: US Stocks, ETFs
- **Features**:
  - Commission-free trading
  - Paper and live trading
  - Real-time and historical data
  - Fractional shares support
  - Crypto trading (limited)
- **Authentication**: API key and secret
- **Rate Limits**: 200 requests/minute
- **Status**: ✅ Production Ready

#### Trading212
- **File**: `trading212.py`
- **Asset Classes**: Stocks, ETFs, CFDs
- **Features**:
  - European market access
  - CFD and Invest account support
  - Real-time market data
  - Multi-currency support
- **Authentication**: API key
- **Rate Limits**: 100 requests/minute
- **Status**: ✅ Production Ready

### Additional Brokers

#### Binance
- **File**: `binance.py`
- **Asset Classes**: Cryptocurrencies, Futures
- **Features**:
  - Spot and futures trading
  - Advanced order types
  - Real-time market data
  - Margin trading support
- **Authentication**: API key and secret with optional IP whitelist
- **Rate Limits**: Variable by endpoint
- **Status**: ⚠️ In Development

#### FXCM
- **File**: `fxcm.py`
- **Asset Classes**: Forex, CFDs
- **Features**:
  - Professional forex trading
  - Advanced charting and analysis
  - Real-time market data
- **Authentication**: API token
- **Rate Limits**: 300 requests/hour
- **Status**: ⚠️ In Development

#### Oanda
- **File**: `oanda.py`
- **Asset Classes**: Forex, CFDs
- **Features**:
  - Professional forex and CFD trading
  - Advanced order management
  - Real-time streaming data
  - Historical data access
- **Authentication**: API token
- **Rate Limits**: 120 requests/minute
- **Status**: 🚧 Planned

#### Coinbase
- **File**: `coinbase.py`
- **Asset Classes**: Cryptocurrencies
- **Features**:
  - Spot cryptocurrency trading
  - Advanced order types
  - Real-time market data
  - Portfolio management
- **Authentication**: API key, secret, and passphrase
- **Rate Limits**: 10 requests/second
- **Status**: 🚧 Planned

## Core Components

### Base Infrastructure

#### Base Adapter (`base.py`)
Provides the abstract base class and common functionality for all broker adapters:
- Connection management
- Health check interface
- Configuration validation
- Event handling

#### Error Handling (`error_handling.py`)
Comprehensive error management system:
- Standardized error representation
- Centralized error handling
- Retry mechanisms with exponential backoff
- Enhanced logging and monitoring

#### Security (`security.py`)
Enterprise-grade security features:
- Secure credential management
- Request signing and authentication
- Security validation utilities
- Audit logging

#### Rate Limiting (`rate_limiting.py`)
Intelligent request management:
- Multiple rate limiting strategies (Token Bucket, Sliding Window, Adaptive)
- Connection pooling and management
- Circuit breaker pattern
- Request metrics and monitoring

#### WebSocket Streaming (`websocket_streaming.py`)
Real-time data streaming infrastructure:
- Unified WebSocket interface
- Automatic reconnection handling
- Message parsing and routing
- Stream health monitoring

#### Configuration Validation (`config_validation.py`)
Robust configuration management:
- Comprehensive validation rules
- Type checking and format validation
- Dependency validation
- Detailed error reporting

#### Health Monitoring (`health_monitoring.py`)
Continuous system monitoring:
- Real-time health checks
- Alert management and notifications
- Performance metrics collection
- System health reporting

## Configuration

### Basic Configuration

Each broker adapter requires specific configuration parameters. Here's a general structure:

```python
from nautilus_trader_engine.adapters.brokers.interactive_brokers import IBConfig
from nautilus_trader_engine.adapters.brokers.security import SecurityConfig, Credentials
from nautilus_trader_engine.adapters.brokers.rate_limiting import RateLimitConfig

# Security configuration
security_config = SecurityConfig(
    authentication_type=AuthenticationType.API_KEY,
    security_level=SecurityLevel.HIGH,
    enable_request_signing=True,
    enable_audit_logging=True
)

# Rate limiting configuration
rate_limit_config = RateLimitConfig(
    strategy=RateLimitStrategy.TOKEN_BUCKET,
    requests_per_second=10.0,
    burst_capacity=50,
    enable_adaptive=True
)

# Broker-specific configuration
config = IBConfig(
    host="127.0.0.1",
    port=7497,
    client_id=1,
    account_id="DU123456",
    security_config=security_config,
    rate_limit_config=rate_limit_config
)
```

### Environment Variables

Sensitive configuration can be provided via environment variables:

```bash
# Interactive Brokers
IB_HOST=127.0.0.1
IB_PORT=7497
IB_CLIENT_ID=1
IB_ACCOUNT_ID=DU123456

# Alpaca
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Trading212
TRADING212_API_KEY=your_api_key
TRADING212_MODE=demo
```

## Usage Examples

### Basic Adapter Setup

```python
import asyncio
from nautilus_trader_engine.adapters.brokers.interactive_brokers import (
    InteractiveBrokersAdapter, IBConfig
)

async def main():
    # Create configuration
    config = IBConfig(
        host="127.0.0.1",
        port=7497,
        client_id=1,
        account_id="DU123456"
    )

    # Create adapter
    adapter = InteractiveBrokersAdapter(config)

    # Connect
    await adapter.connect()

    # Check health
    health = await adapter.health_check()
    print(f"Adapter health: {health}")

    # Disconnect
    await adapter.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

### Health Monitoring Setup

```python
from nautilus_trader_engine.adapters.brokers.health_monitoring import BrokerHealthMonitor

# Create health monitor
monitor = BrokerHealthMonitor()

# Register brokers
ib_checker = monitor.register_broker("interactive_brokers")
alpaca_checker = monitor.register_broker("alpaca")

# Add custom alert handler
def custom_alert_handler(alert):
    print(f"ALERT: {alert.title} - {alert.message}")

monitor.add_alert_handler(custom_alert_handler)

# Start monitoring
await monitor.start_monitoring()

# Get system health summary
summary = monitor.get_system_health_summary()
print(f"System health: {summary}")
```

### WebSocket Streaming

```python
from nautilus_trader_engine.adapters.brokers.websocket_streaming import (
    WebSocketStreamManager, StreamConfig
)

# Create stream manager
stream_manager = WebSocketStreamManager()

# Configure stream
config = StreamConfig(
    broker_id="interactive_brokers",
    stream_types=[StreamType.MARKET_DATA, StreamType.ACCOUNT_UPDATES],
    symbols=["AAPL", "GOOGL", "MSFT"],
    auto_reconnect=True,
    max_reconnect_attempts=5
)

# Start streaming
stream = await stream_manager.create_stream(config)
await stream.start()

# Handle messages
async for message in stream.message_queue:
    print(f"Received: {message}")
```

## Testing

Comprehensive test suite is available in the `tests/` directory:

```bash
# Run all tests
python tests/run_tests.py

# Run specific broker tests
python tests/run_tests.py --broker interactive_brokers

# Run with coverage
python tests/run_tests.py --coverage

# Run integration tests (requires broker credentials)
python tests/run_tests.py --integration
```

### Test Categories

- **Unit Tests**: Test individual components and functions
- **Integration Tests**: Test broker connectivity and operations
- **Security Tests**: Validate security implementations
- **Performance Tests**: Measure latency and throughput
- **Error Handling Tests**: Verify error scenarios and recovery

## Security Considerations

### Credential Management
- Never hardcode API keys or secrets in source code
- Use environment variables or secure credential stores
- Implement credential rotation where supported
- Enable audit logging for all authentication events

### Network Security
- Use HTTPS/WSS for all communications
- Implement request signing where available
- Validate SSL certificates
- Consider IP whitelisting for production environments

### Data Protection
- Encrypt sensitive data at rest
- Implement secure logging (no sensitive data in logs)
- Use secure random number generation
- Follow principle of least privilege

## Performance Optimization

### Connection Management
- Use connection pooling where applicable
- Implement proper connection lifecycle management
- Monitor connection health and implement auto-recovery
- Optimize reconnection strategies

### Rate Limiting
- Implement intelligent rate limiting strategies
- Use adaptive rate limiting based on broker responses
- Implement request queuing and prioritization
- Monitor and alert on rate limit violations

### Data Handling
- Use efficient data structures for market data
- Implement data compression where applicable
- Optimize memory usage for high-frequency data
- Use appropriate data serialization formats

## Troubleshooting

### Common Issues

#### Connection Problems
- **Symptom**: Unable to connect to broker
- **Solutions**:
  - Verify network connectivity
  - Check firewall settings
  - Validate credentials
  - Ensure broker service is running

#### Authentication Failures
- **Symptom**: Authentication errors
- **Solutions**:
  - Verify API credentials
  - Check credential expiration
  - Validate IP whitelist settings
  - Review audit logs

#### Rate Limiting
- **Symptom**: Rate limit exceeded errors
- **Solutions**:
  - Reduce request frequency
  - Implement request queuing
  - Use adaptive rate limiting
  - Contact broker for limit increases

#### Data Quality Issues
- **Symptom**: Missing or incorrect market data
- **Solutions**:
  - Verify data subscriptions
  - Check market hours
  - Validate symbol formats
  - Review data feed configuration

### Logging and Debugging

Enable detailed logging for troubleshooting:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable broker-specific logging
logging.getLogger('nautilus_trader_engine.adapters.brokers').setLevel(logging.DEBUG)
```

## Contributing

### Adding New Brokers

1. **Create Adapter Class**: Inherit from `BaseBrokerAdapter`
2. **Implement Required Methods**: Connection, authentication, order management
3. **Add Configuration**: Create broker-specific config class
4. **Implement Tests**: Unit, integration, and security tests
5. **Update Documentation**: Add broker to this README

### Code Standards

- Follow PEP 8 style guidelines
- Use type hints for all public APIs
- Implement comprehensive error handling
- Add docstrings for all public methods
- Include unit tests for new functionality

### Pull Request Process

1. Fork the repository
2. Create feature branch
3. Implement changes with tests
4. Update documentation
5. Submit pull request with detailed description

## Support

For support and questions:

- **Documentation**: Check this README and inline documentation
- **Issues**: Create GitHub issues for bugs and feature requests
- **Testing**: Use the comprehensive test suite
- **Monitoring**: Leverage health monitoring and alerting

## License

This project is licensed under the MIT License. See LICENSE file for details.

## Changelog

### Version 1.0.0 (Current)
- Initial release with comprehensive broker adapter framework
- Support for Interactive Brokers, Alpaca, and Trading212
- Enterprise-grade security and monitoring features
- Comprehensive test suite and documentation

### Planned Features
- Oanda and Coinbase adapter implementations
- Enhanced WebSocket streaming capabilities
- Advanced order management features
- Performance optimization improvements
