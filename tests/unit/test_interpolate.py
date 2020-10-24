from math import inf, pi

import pytest

from dvc.parsing import Context


@pytest.mark.parametrize(
    "template, var",
    [
        ("${value}", "value"),
        ("${{item}}", "item"),
        ("${ item }", "item"),
        ("${{ value }}", "value"),
    ],
)
@pytest.mark.parametrize(
    "data", [True, 12, pi, None, False, 0, "0", "123", "Foobar", "", inf, 3e4]
)
def test_resolve_primitive_values(data, template, var):
    context = Context({var: data})
    assert context.format(template) == data


@pytest.mark.parametrize(
    "template, expected",
    [
        (r"\${value}", "${value}"),
        (r"\${{value}}", "${{value}}"),
        (r"\${ value }", "${ value }"),
        (r"\${{ value }}", "${{ value }}"),
        (r"\${{ value }} days", "${{ value }} days"),
        (r"\${ value } days", "${ value } days"),
        (r"Month of \${value}", "Month of ${value}"),
        (r"May the \${value} be with you", "May the ${value} be with you"),
        (
            r"Great shot kid, that was \${value} in a ${value}",
            "Great shot kid, that was ${value} in a value",
        ),
    ],
)
def test_escape(template, expected, mocker):
    context = Context({"value": "value"})
    assert context.format(template) == expected


def test_resolve_str():
    template = "My name is ${last}, ${first} ${last}"
    expected = "My name is Bond, James Bond"
    context = Context({"first": "James", "last": "Bond"})
    assert context.format(template) == expected


def test_resolve_primitives_dict_access():
    data = {
        "dict": {
            "num": 5,
            "string": "foo",
            "nested": {"float": pi, "string": "bar"},
        }
    }
    context = Context(data)

    assert context.format("${dict.num}") == 5
    assert context.format("${dict.string}") == "foo"
    assert context.format("${dict.nested.float}") == pi
    assert context.format("${dict.nested.string}") == "bar"
    assert context.format("Number ${dict.num}") == "Number 5"


def test_resolve_primitives_list_access():
    context = Context(
        {
            "dict": [
                {"f": "f"},
                {"fo": "fo"},
                {"foo": "foo"},
                {"foo": ["f", "o", "o"]},
            ]
        }
    )

    assert context.format("${dict.0.f}") == "f"
    assert context.format("${dict.1.fo}") == "fo"
    assert context.format("${dict.2.foo}") == "foo"
    assert context.format("${dict.3.foo.0}") == "f"

    assert context.format("${ dict.1.fo}${dict.3.foo.1}bar") == "foobar"


def test_resolve_collection():
    from .test_stage_resolver import (
        CONTEXT_DATA,
        RESOLVED_DVC_YAML_DATA,
        TEMPLATED_DVC_YAML_DATA,
    )

    context = Context(CONTEXT_DATA)
    assert context.format(TEMPLATED_DVC_YAML_DATA) == RESOLVED_DVC_YAML_DATA
