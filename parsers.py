"""Safe parsing helpers for HAVCS configuration values."""

import ast
import json


def parse_custom_action_data(value):
    """Parse custom service data without evaluating executable code.

    Existing HAVCS configurations commonly store Python-style dictionary
    literals; JSON is also accepted for newer configurations.
    """
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError) as err:
                raise ValueError("custom action data must be a dictionary literal") from err
    else:
        raise ValueError("custom action data must be a dictionary literal")

    if not isinstance(parsed, dict):
        raise ValueError("custom action data must evaluate to a dictionary")
    return parsed
