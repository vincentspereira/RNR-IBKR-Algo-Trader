"""Data factories for creating test data."""
from typing import Dict, Any
from uuid import uuid4
from datetime import datetime
from faker import Faker

fake = Faker()


class UserFactory:
    """Factory for creating test users."""
    
    @staticmethod
    def create(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a test user."""
        user = {
            'user_id': str(uuid4()),
            'email': fake.email(),
            'username': fake.user_name(),
            'first_name': fake.first_name(),
            'last_name': fake.last_name(),
            'is_active': True,
            'created_at': datetime.utcnow(),
        }
        if overrides:
            user.update(overrides)
        return user


class OrderFactory:
    """Factory for creating test orders."""
    
    @staticmethod
    def create(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a test order."""
        order = {
            'order_id': str(uuid4()),
            'user_id': str(uuid4()),
            'symbol': fake.random_element(['AAPL', 'GOOGL', 'MSFT', 'TSLA']),
            'order_type': fake.random_element(['MARKET', 'LIMIT']),
            'side': fake.random_element(['BUY', 'SELL']),
            'quantity': fake.random_int(min=1, max=1000),
            'price': fake.pyfloat(min_value=10, max_value=500, right_digits=2),
            'status': 'PENDING',
            'created_at': datetime.utcnow(),
        }
        if overrides:
            order.update(overrides)
        return order


class StrategyFactory:
    """Factory for creating test strategies."""
    
    @staticmethod
    def create(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a test strategy."""
        strategy = {
            'strategy_id': str(uuid4()),
            'user_id': str(uuid4()),
            'name': fake.catch_phrase(),
            'description': fake.text(),
            'strategy_type': fake.random_element(['TECHNICAL', 'FUNDAMENTAL', 'ML', 'HYBRID']),
            'is_active': False,
            'created_at': datetime.utcnow(),
        }
        if overrides:
            strategy.update(overrides)
        return strategy


class MarketDataFactory:
    """Factory for creating test market data."""
    
    @staticmethod
    def create_tick(overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create test tick data."""
        tick = {
            'symbol': fake.random_element(['AAPL', 'GOOGL', 'MSFT']),
            'price': fake.pyfloat(min_value=10, max_value=500, right_digits=2),
            'volume': fake.random_int(min=100, max=10000),
            'timestamp': datetime.utcnow(),
        }
        if overrides:
            tick.update(overrides)
        return tick
