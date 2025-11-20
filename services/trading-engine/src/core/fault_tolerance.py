class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

    def allow_request(self) -> bool:
        return True

    def record_success(self):
        pass

    def record_failure(self):
        pass

class HealthMonitor:
    def __init__(self):
        pass

    def check_health(self):
        return True
