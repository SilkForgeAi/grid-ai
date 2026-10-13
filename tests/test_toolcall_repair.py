"""A tool call whose arguments are one valid JSON object plus junk is kept; broken ones aren't."""

from __future__ import annotations

import json

import pytest

from grid.toolcall_repair import first_object, install, lenient

pytest.importorskip("openhands.sdk")


def test_first_object_only_takes_a_complete_leading_object():
    assert first_object('{"command": "view", "path": "a.py"}}') == {"command": "view", "path": "a.py"}
    assert first_object('{"a": 1}{"b": 2}') == {"a": 1}
    assert first_object('  {"a": "x}y"} and some words') == {"a": "x}y"}
    assert first_object('{"a": 1, "b": ') is None
    assert first_object('text {"a": 1}') is None
    assert first_object("[1, 2]") is None


def test_the_sdk_parser_keeps_good_calls_and_rescues_trailing_junk():
    from openhands.sdk.agent.utils import parse_tool_call_arguments

    parse = lenient(parse_tool_call_arguments)
    good = {"command": "str_replace", "path": "main.py", "old_str": "a - b", "new_str": "a + b"}
    assert parse(json.dumps(good)) == parse_tool_call_arguments(json.dumps(good))
    assert parse(json.dumps(good) + "}") == parse_tool_call_arguments(json.dumps(good))
    with pytest.raises(json.JSONDecodeError):
        parse('{"command": "str_replace", "path": ')


def test_install_wraps_once():
    import openhands.sdk.agent.agent as agent_module

    install()
    first = agent_module.parse_tool_call_arguments
    install()
    assert agent_module.parse_tool_call_arguments is first and first._grid_lenient
