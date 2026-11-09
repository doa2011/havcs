"""Unit tests for HAVCS configuration parsers."""

import unittest

from parsers import parse_custom_action_data


class CustomActionDataTests(unittest.TestCase):
    def test_parses_legacy_python_dictionary_literal(self):
        self.assertEqual(
            parse_custom_action_data("{'entity_id': 'light.living_room', 'enabled': True}"),
            {"entity_id": "light.living_room", "enabled": True},
        )

    def test_parses_json_dictionary(self):
        self.assertEqual(
            parse_custom_action_data('{"entity_id": "light.living_room", "enabled": false, "value": null}'),
            {"entity_id": "light.living_room", "enabled": False, "value": None},
        )

    def test_accepts_dictionary_value(self):
        value = {"brightness": 0}
        self.assertIs(parse_custom_action_data(value), value)

    def test_rejects_non_dictionary(self):
        with self.assertRaises(ValueError):
            parse_custom_action_data("[]")

    def test_rejects_executable_expression(self):
        with self.assertRaises(ValueError):
            parse_custom_action_data("__import__('os').system('echo unsafe')")


if __name__ == "__main__":
    unittest.main()
