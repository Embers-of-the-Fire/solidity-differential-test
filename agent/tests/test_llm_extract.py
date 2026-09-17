import pytest

from agent.llm import LLMError, extract_json


def test_extract_fenced_json():
    text = 'Here you go:\n```json\n{"name": "x", "steps": []}\n```\nDone.'
    assert extract_json(text) == {"name": "x", "steps": []}


def test_extract_raw_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_surrounding_prose():
    text = 'The spec is {"a": 2} as requested.'
    assert extract_json(text) == {"a": 2}


def test_extract_json_ignores_non_object_json():
    # a bare array is not a valid spec
    assert extract_json('[1, 2] then {"b": 3}') == {"b": 3}


def test_extract_json_garbage_raises():
    with pytest.raises(LLMError):
        extract_json("no json here at all")
