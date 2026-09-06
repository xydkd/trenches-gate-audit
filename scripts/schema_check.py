"""Draft 2020-12 validation with timezone-aware datetime parsing."""
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return result


def check(value, schema):
    Draft202012Validator.check_schema(schema)
    return [f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
            for e in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)]
