from __future__ import annotations

import pytest

from devpilot.agent import ActionParseError, parse_action


def test_bare_json() -> None:
    action = parse_action('{"thought": "t", "tool": "read_file", "args": {"path": "a.py"}}')
    assert action.tool == "read_file"
    assert action.args == {"path": "a.py"}
    assert action.thought == "t"


def test_fenced_json_with_prose() -> None:
    text = 'Sure! Here is my action:\n```json\n{"tool": "run_tests", "args": {}}\n```'
    assert parse_action(text).tool == "run_tests"


def test_embedded_json_and_aliases() -> None:
    action = parse_action('I will finish now {"action": "finish", "arguments": {"summary": "x"}}')
    assert action.is_finish
    assert action.args["summary"] == "x"


@pytest.mark.parametrize("bad", ["no json here", '{"args": {}}', '{"tool": "x", "args": [1]}'])
def test_invalid_replies(bad: str) -> None:
    with pytest.raises(ActionParseError):
        parse_action(bad)
