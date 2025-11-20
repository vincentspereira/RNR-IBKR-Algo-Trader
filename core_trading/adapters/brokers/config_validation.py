import inspect
import ipaddress
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
from urllib.parse import urlparse
"Configuration validation and error reporting for broker adapters"

# This module provides comprehensive validation for broker adapter configurations,
# including credential validation, parameter checking, and detailed error reporting."




# "

class ValidationSeverity(Enum):""
# "Validation error severity levels
# "
#     INFO = "info"
#     WARNING = "warning"
#     ERROR = "error"
#     CRITICAL = "critical"


# "

class ValidationType(Enum):""
# "Types of validation checks
# "
#     REQUIRED = "required"
#     TYPE_CHECK = "type_check"
#     RANGE = "range"
#     FORMAT = "format"
#     CUSTOM = "custom"
#     DEPENDENCY = "dependency"
#     SECURITY = "security"
#     NETWORK = "network"
#     FILE_PATH = "file_path"


# "

# @dataclass
class ValidationRule:""
#     "Individual validation rule"

#     field_name: str
#     validation_type: ValidationType
#     severity: ValidationSeverity = ValidationSeverity.ERROR
#     message: Optional[str] = None
#     validator: Optional[Callable[[Any], bool]] = None
#     expected_type: Optional[Type] = None
#     min_value: Optional[Union[int, float]] = None
#     max_value: Optional[Union[int, float]] = None
#     pattern: Optional[str] = None
#     allowed_values: Optional[List[Any]] = None
#     dependencies: Optional[List[str]] = None
#     custom_message: Optional[str] = None


# @dataclass
class ValidationError:""
#     "Validation error details"

#     field_name: str
#     error_type: ValidationType
#     severity: ValidationSeverity
#     message: str
#     current_value: Any = None
#     expected_value: Any = None
#     suggestion: Optional[str] = None
#     documentation_link: Optional[str] = None


# @dataclass
class ValidationResult:""
#     "Complete validation result"

#     is_valid: bool
#     errors: List[ValidationError] = field(default_factory=list)
#     warnings: List[ValidationError] = field(default_factory=list)
# info: List[ValidationError] = field(default_factory=list)"
# summary: str = "

#     def add_error(self, error: ValidationError):
#         "Add validation error"
#         if (
#             error.severity == ValidationSeverity.ERROR
# or error.severity == ValidationSeverity.CRITICAL
# ):
#             self.errors.append(error)
#             self.is_valid = False
#         elif error.severity == ValidationSeverity.WARNING:
#             self.warnings.append(error)
#         else:
#             self.info.append(error)

#     def get_all_issues(self):
#         "Get all validation issues"
#         return self.errors + self.warnings + self.info

#     def has_critical_errors(self):
#         "Check if there are critical errors"
#         return any(
# error.severity == ValidationSeverity.CRITICAL for error in self.errors
# )

#     def generate_summary(self):
# "Generate validation summary
#         if self.is_valid:""
# summary = "[SUCCESS] Configuration validation passed
#             if self.warnings:""
#                 summary += f" with {len(self.warnings)} warnings"
#         else:
# summary = ("
#                 f"[FAIL] Configuration validation failed with {len(self.errors)} errors"
# )
#             if self.warnings:""
#                 summary += f" and {len(self.warnings)} warnings"

#         self.summary = summary
#         return summary


class BaseValidator(ABC):""
#     "Base class for configuration validators"

#     @abstractmethod
#     def validate(self, value: Any, rule: ValidationRule):
#         "Validate a value against a rule"
#         pass


class RequiredValidator(BaseValidator):""
#     "Validator for required fields"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or (isinstance(value, str) and not value.strip()):
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.REQUIRED,
# severity=rule.severity,"
#                 message=rule.custom_message or f"Field '{rule.field_name}' is required",
# current_value=value,"
#                 suggestion="Please provide a valid value for this required field",
# )
#         return None


class TypeValidator(BaseValidator):""
#     "Validator for type checking"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or rule.expected_type is None:
#             return None

#         if not isinstance(value, rule.expected_type):
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.TYPE_CHECK,
#                 severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Field '{rule.field_name}' must be of type {rule.expected_type.__name__}","
#                 current_value=f"{type(value).__name__}: {value}",
# expected_value=rule.expected_type.__name__,"
#                 suggestion=f"Convert the value to {rule.expected_type.__name__}",
# )
#         return None


class RangeValidator(BaseValidator):""
#     "Validator for numeric ranges"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or not isinstance(value, (int, float)):
#             return None

#         if rule.min_value is not None and value < rule.min_value:
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.RANGE,
#                 severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Field '{rule.field_name}' must be >= {rule.min_value}",
# current_value=value,"
# expected_value=f">= {rule.min_value}","
#                 suggestion=f"Use a value >= {rule.min_value}",
# )

#         if rule.max_value is not None and value > rule.max_value:
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.RANGE,
#                 severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Field '{rule.field_name}' must be <= {rule.max_value}",
# current_value=value,"
# expected_value=f"<= {rule.max_value}","
#                 suggestion=f"Use a value <= {rule.max_value}",
# )

#         return None


class FormatValidator(BaseValidator):""
#     "Validator for string formats and patterns"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or not isinstance(value, str):
#             return None

#         if rule.pattern:
#             if not re.match(rule.pattern, value):
#                 return ValidationError(
#                     field_name=rule.field_name,
#                     error_type=ValidationType.FORMAT,
#                     severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Field '{rule.field_name}' does not match required format",
# current_value=value,"
# expected_value=f"Pattern: {rule.pattern}","
#                     suggestion="Check the format requirements and adjust the value",
# )

#         if rule.allowed_values and value not in rule.allowed_values:
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.FORMAT,
#                 severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Field '{rule.field_name}' must be one of: {rule.allowed_values}",
# current_value=value,"
# expected_value=f"One of: {rule.allowed_values}","
#                 suggestion=f"Use one of the allowed values: {rule.allowed_values}",
# )

#         return None


class CustomValidator(BaseValidator):""
#     "Validator for custom validation functions"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if rule.validator is None:
#             return None

#         try:
#             if not rule.validator(value):
#                 return ValidationError(
#                     field_name=rule.field_name,
#                     error_type=ValidationType.CUSTOM,
#                     severity=rule.severity,
# message=rule.custom_message"'"'
# or f"Custom validation failed for field '{rule.field_name}'",
# current_value=value,"
#                     suggestion="Check the custom validation requirements",
# )
#         except Exception as e:
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.CUSTOM,
# severity=ValidationSeverity.ERROR,"'"'
#                 message=f"Custom validator error for field '{rule.field_name}': {e}",
# current_value=value,"
#                 suggestion="Fix the custom validator or the input value",
# )

#         return None


class NetworkValidator(BaseValidator):""
#     "Validator for network-related configurations"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or not isinstance(value, str):
#             return None

        # URL validation"
#         if rule.field_name.lower() in ["url", "endpoint", "api_url", "websocket_url"]:
#             try:
#                 parsed = urlparse(value)
#                 if not parsed.scheme or not parsed.netloc:
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.NETWORK,
# severity=rule.severity,"'"'
#                         message=f"Invalid URL format for field '{rule.field_name}'",
# current_value=value,"
#                         suggestion="Use a valid URL format (e.g., https://example.com)",
# )

                # Check for secure protocols in production"
#                 if parsed.scheme not in ["https", "wss"] and "prod" in value.lower():
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.SECURITY,
# severity=ValidationSeverity.WARNING,"'"'
#                         message=f"Insecure protocol used for field '{rule.field_name}' in production",
# current_value=value,"
#                         suggestion="Use HTTPS or WSS for production environments",
# )

#             except Exception:
#                 return ValidationError(
#                     field_name=rule.field_name,
#                     error_type=ValidationType.NETWORK,
# severity=rule.severity,"'"'
#                     message=f"Invalid URL for field '{rule.field_name}'",
# current_value=value,"
#                     suggestion="Provide a valid URL",
# )

        # IP address validation"
#         if rule.field_name.lower() in ["ip", "host", "server_ip"]:
#             try:
#                 ipaddress.ip_address(value)
#             except ValueError:
                # Try as hostname"
#                 if not re.match(r"^[a-zA-Z0-9.-]+$", value):
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.NETWORK,
# severity=rule.severity,"'"'
#                         message=f"Invalid IP address or hostname for field '{rule.field_name}'",
# current_value=value,"
#                         suggestion="Provide a valid IP address or hostname",
# )

#         return None


class FilePathValidator(BaseValidator):""
#     "Validator for file paths"

#     def validate(self, value: Any, rule: ValidationRule) -> Optional[ValidationError]:
#         if value is None or not isinstance(value, str):
#             return None

#         try:
#             path = Path(value)

            # Check if file should exist"
#             if rule.field_name.lower() in [""
# "config_file","
# "cert_file","
# "key_file","
#                 "ca_file",
# ]:
#                 if not path.exists():
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.FILE_PATH,
# severity=rule.severity,"'"'
#                         message=f"File not found for field '{rule.field_name}'",
# current_value=value,"
#                         suggestion="Ensure the file exists at the specified path",
# )

#                 if not path.is_file():
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.FILE_PATH,
# severity=rule.severity,"'"'
#                         message=f"Path is not a file for field '{rule.field_name}'",
# current_value=value,"
#                         suggestion="Provide a path to a file, not a directory",
# )

            # Check directory paths"
#             if rule.field_name.lower() in ["log_dir", "data_dir", "cache_dir"]:
#                 if path.exists() and not path.is_dir():
#                     return ValidationError(
#                         field_name=rule.field_name,
#                         error_type=ValidationType.FILE_PATH,
# severity=rule.severity,"'"'
#                         message=f"Path is not a directory for field '{rule.field_name}'",
# current_value=value,"
#                         suggestion="Provide a path to a directory",
# )

#         except Exception as e:
#             return ValidationError(
#                 field_name=rule.field_name,
#                 error_type=ValidationType.FILE_PATH,
# severity=rule.severity,"'"'
#                 message=f"Invalid path for field '{rule.field_name}': {e}",
# current_value=value,"
#                 suggestion="Provide a valid file system path",
# )

#         return None


class ConfigValidator:""
#     "Main configuration validator"

#     def __init__(self):
#         self.validators = {
# ValidationType.REQUIRED: RequiredValidator(),
# ValidationType.TYPE_CHECK: TypeValidator(),
# ValidationType.RANGE: RangeValidator(),
# ValidationType.FORMAT: FormatValidator(),
# ValidationType.CUSTOM: CustomValidator(),
# ValidationType.NETWORK: NetworkValidator(),
# ValidationType.FILE_PATH: FilePathValidator(),
# }
#         self._logger = logging.getLogger(__name__)

#     def validate_config(
# self, config: Any, rules: List[ValidationRule]
# ) -> ValidationResult:"
#         "Validate configuration against rules"
# result = ValidationResult(is_valid=True)'

        # Convert config to dict if it's a dataclass"
#         if hasattr(config, "__dataclass_fields__"):
# config_dict = {
#                 field.name: getattr(config, field.name)
#                 for field in config.__dataclass_fields__.values()
# }
#         elif isinstance(config, dict):
#             config_dict = config
#         else:
            # Try to convert to dict
#             try:
#                 config_dict = vars(config)
#             except TypeError:
# result.add_error(
# ValidationError("
#                         field_name="config",
#                         error_type=ValidationType.TYPE_CHECK,
# severity=ValidationSeverity.CRITICAL,"
#                         message="Configuration must be a dataclass, dict, or object with attributes",
#                         current_value=type(config).__name__,
# )
# )
#                 return result

        # Validate each rule
#         for rule in rules:
#             value = config_dict.get(rule.field_name)

            # Get appropriate validator
#             validator = self.validators.get(rule.validation_type)
#             if validator is None:
#                 self._logger.warning(""
#                     f"No validator found for type: {rule.validation_type}"
# )
#                 continue

            # Perform validation
#             error = validator.validate(value, rule)
#             if error:
#                 result.add_error(error)

        # Check dependencies
#         self._validate_dependencies(config_dict, rules, result)

        # Generate summary
#         result.generate_summary()

#         return result

#     def _validate_dependencies(
#         self,
# config_dict: Dict[str, Any],
# rules: List[ValidationRule],
# result: ValidationResult,
# ):"
#         "Validate field dependencies"
#         for rule in rules:
#             if rule.dependencies:
#                 value = config_dict.get(rule.field_name)

                # If field has value, check dependencies
#                 if value is not None:
#                     for dep_field in rule.dependencies:
#                         dep_value = config_dict.get(dep_field)
#                         if dep_value is None:
# result.add_error(
# ValidationError(
#                                     field_name=rule.field_name,
#                                     error_type=ValidationType.DEPENDENCY,
# severity=ValidationSeverity.ERROR,"'"'
#                                     message=f"Field '{rule.field_name}' requires '{dep_field}' to be set",
# current_value=value,"'"'
#                                     suggestion=f"Set a value for '{dep_field}'",
# )
# )


class BrokerConfigValidator:""
#     "Specialized validator for broker configurations"

#     def __init__(self):
#         self.validator = ConfigValidator()
#         self._logger = logging.getLogger(__name__)

#     def get_common_broker_rules(self):
#         "Get common validation rules for all brokers"
#         return [
            # API credentials"
# ValidationRule("
#                 field_name="api_key",
#                 validation_type=ValidationType.REQUIRED,
# severity=ValidationSeverity.CRITICAL,"
# ""custom_message="API key is required for broker connection","
# ),
# ValidationRule("
#                 field_name="api_secret",
#                 validation_type=ValidationType.REQUIRED,
# severity=ValidationSeverity.CRITICAL,"
# ""custom_message="API secret is required for broker connection","
# ),
            # Connection settings"
# ValidationRule("
#                 field_name="base_url",
#                 validation_type=ValidationType.NETWORK,
#                 severity=ValidationSeverity.ERROR,
# ),
# ValidationRule("
#                 field_name="timeout",
#                 validation_type=ValidationType.RANGE,
#                 expected_type=float,
#                 min_value=1.0,
#                 max_value=300.0,
#                 severity=ValidationSeverity.WARNING,
# ),
            # Rate limiting"
# ValidationRule("
#                 field_name="requests_per_second",
#                 validation_type=ValidationType.RANGE,
#                 expected_type=float,
#                 min_value=0.1,
#                 max_value=1000.0,
#                 severity=ValidationSeverity.WARNING,
# ),
            # Trading settings"
# ValidationRule("
#                 field_name="is_paper_trading",
#                 validation_type=ValidationType.TYPE_CHECK,
#                 expected_type=bool,
#                 severity=ValidationSeverity.ERROR,
# ),
# ]

#     def get_interactive_brokers_rules(self):
#         "Get validation rules specific to Interactive Brokers"
#         common_rules = self.get_common_broker_rules()
# ib_rules = [
# ValidationRule("
#                 field_name="host",
#                 validation_type=ValidationType.NETWORK,
# severity=ValidationSeverity.ERROR,"
#                 custom_message="TWS/Gateway host is required",
# ),
# ValidationRule("
#                 field_name="port",
#                 validation_type=ValidationType.RANGE,
#                 expected_type=int,
#                 min_value=1,
#                 max_value=65535,
#                 severity=ValidationSeverity.ERROR,
# ),
# ValidationRule("
#                 field_name="client_id",
#                 validation_type=ValidationType.RANGE,
#                 expected_type=int,
#                 min_value=0,
#                 max_value=32,
#                 severity=ValidationSeverity.ERROR,
# ),
# ]
#         return common_rules + ib_rules

#     def get_alpaca_rules(self):
#         "Get validation rules specific to Alpaca"
#         common_rules = self.get_common_broker_rules()
# alpaca_rules = [
# ValidationRule("
#                 field_name="base_url",
#                 validation_type=ValidationType.FORMAT,
# allowed_values=["
# "https://paper-api.alpaca.markets","
#                     "https://api.alpaca.markets",
# ],
# severity=ValidationSeverity.ERROR,"
#                 custom_message="Base URL must be official Alpaca endpoint",
# ),
# ]
#         return common_rules + alpaca_rules

#     def validate_broker_config(self, broker_name: str, config: Any):
# "Validate broker-specific configuration
        # Get appropriate rules based on broker"
#         if broker_name.lower() == "interactive_brokers":
# rules = self.get_interactive_brokers_rules()"
#         elif broker_name.lower() == "alpaca":
#             rules = self.get_alpaca_rules()
#         else:
            # Use common rules for unknown brokers
#             rules = self.get_common_broker_rules()
#             self._logger.warning(""
#                 f"Using common rules for unknown broker: {broker_name}"
# )

#         return self.validator.validate_config(config, rules)

#     def generate_config_report(self, broker_name: str, config: Any):
#         "Generate detailed configuration validation report"
#         result = self.validate_broker_config(broker_name, config)

# report = []"
# report.append(f"Configuration Validation Report for {broker_name}")"
# report.append("=" * (40 + len(broker_name)))"
# report.append(")
# report.append(result.summary)"
# report.append(")

#         if result.errors:""
#             report.append("[FAIL] ERRORS:")
#             for error in result.errors:""
#                 report.append(f"  • {error.field_name}: {error.message}")
#                 if error.suggestion:""
# report.append(f"    [IDEA] {error.suggestion}")"
# report.append(")

#         if result.warnings:""
#             report.append("[WARN]️  WARNINGS:")
#             for warning in result.warnings:""
#                 report.append(f"  • {warning.field_name}: {warning.message}")
#                 if warning.suggestion:""
# report.append(f"    [IDEA] {warning.suggestion}")"
# report.append(")

#         if result.info:""
#             report.append("ℹ️  INFO:")
#             for info in result.info:""
# report.append(f"  • {info.field_name}: {info.message}")"
# report.append(")
# "
#         return "\n".join(report)


# Utility functions for common validations"
# def validate_api_key_format(api_key: str):
# "Validate API key format""
#     if not api_key or len(api_key) < 10:
#         return False
    # Add more specific validation based on broker requirements
#     return True


# def validate_url_accessibility(url: str):
#     "Validate if URL is accessible (basic check)"
#     try:
#         parsed = urlparse(url)
#         return bool(parsed.scheme and parsed.netloc)
#     except Exception:
#         return False


# def validate_port_range(port: int):
#     "Validate port is in valid range"
#     return 1 <= port <= 65535


# def validate_positive_number(value: Union[int, float]):
#     "Validate number is positive"
#     return isinstance(value, (int, float)) and value > 0
# "'"'