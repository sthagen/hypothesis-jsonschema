"""Tests for the hypothesis-jsonschema library."""

import json
import re
from pathlib import Path

import jsonschema
import pytest
import strict_rfc3339
from gen_schemas import schema_strategy_params
from hypothesis import (
    HealthCheck,
    assume,
    given,
    note,
    reject,
    settings,
    strategies as st,
)
from hypothesis.errors import FailedHealthCheck, InvalidArgument
from hypothesis.internal.reflection import proxies

from hypothesis_jsonschema._canonicalise import (
    HypothesisRefResolutionError,
    canonicalish,
    resolve_all_refs,
)
from hypothesis_jsonschema._from_schema import from_schema, rfc3339


@settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    deadline=None,
)
@given(data=st.data())
@schema_strategy_params
def test_generated_data_matches_schema(schema_strategy, data):
    """Check that an object drawn from an arbitrary schema is valid."""
    schema = data.draw(schema_strategy)
    note(schema)
    try:
        value = data.draw(from_schema(schema), "value from schema")
    except InvalidArgument:
        reject()
    try:
        jsonschema.validate(value, schema)
        # This checks that our canonicalisation is semantically equivalent.
        jsonschema.validate(value, canonicalish(schema))
    except jsonschema.ValidationError as err:
        if "'uniqueItems': True" in str(err):
            pytest.xfail("https://github.com/Julian/jsonschema/issues/686")
        raise


@given(from_schema(True))
def test_boolean_true_is_valid_schema_and_resolvable(_):
    """...even though it's currently broken in jsonschema."""


@pytest.mark.parametrize(
    "schema",
    [
        None,
        False,
        {"type": "an unknown type"},
        {"allOf": [{"type": "boolean"}, {"const": None}]},
        {"allOf": [{"type": "boolean"}, {"enum": [None]}]},
    ],
)
def test_invalid_schemas_raise(schema):
    """Trigger all the validation exceptions for full coverage."""
    with pytest.raises(Exception):
        from_schema(schema).example()


INVALID_SCHEMAS = {
    # Empty list for requires, which is invalid
    "Release Drafter configuration file",
    # Many, many schemas have invalid $schema keys, which emit a warning (-Werror)
    "A JSON schema for CRYENGINE projects (.cryproj files)",
    "JSDoc configuration file",
    "Meta-validation schema for JSON Schema Draft 8",
    "Static Analysis Results Format (SARIF) External Property File Format, Version 2.1.0-rtm.2",
    "Static Analysis Results Format (SARIF) External Property File Format, Version 2.1.0-rtm.3",
    "Static Analysis Results Format (SARIF) External Property File Format, Version 2.1.0-rtm.4",
    "Static Analysis Results Format (SARIF) External Property File Format, Version 2.1.0-rtm.5",
    "Static Analysis Results Format (SARIF), Version 2.1.0-rtm.2",
    "Zuul CI configuration file",
}
NON_EXISTENT_REF_SCHEMAS = {
    "Cirrus CI configuration files",
    "The Bamboo Specs allows you to define Bamboo configuration as code, and have corresponding plans/deployments created or updated automatically in Bamboo",
    # Special case - reference is valid, but target is list-format `items` rather than a subschema
    "TypeScript Lint configuration file",
}
UNSUPPORTED_SCHEMAS = {
    # Technically valid, but using regex patterns not supported by Python
    "draft7/ECMA 262 regex escapes control codes with \\c and lower letter",
    "draft7/ECMA 262 regex escapes control codes with \\c and upper letter",
}
FLAKY_SCHEMAS = {
    # The following schemas refer to an `$id` rather than a JSON pointer.
    # This is valid, but not supported by the Python library - see e.g.
    # https://json-schema.org/understanding-json-schema/structuring.html#using-id-with-ref
    "draft4/Location-independent identifier",
    "draft7/Location-independent identifier",
    # Yep, lists of lists of lists of lists of lists of integers are HealthCheck-slow
    # TODO: write a separate test with healthchecks disabled?
    "draft4/nested items",
    "draft7/nested items",
    "draft4/oneOf with missing optional property",
    "draft7/oneOf with missing optional property",
    # Sometimes unsatisfiable.  TODO: improve canonicalisation to remove filters
    "Drone CI configuration file",
    "PHP Composer configuration file",
    "Pyrseas database schema versioning for Postgres databases, v0.8",
    # Apparently we're not handling this one correctly?
    "draft4/additionalProperties should not look in applicators",
    "draft7/additionalProperties should not look in applicators",
}
SLOW_SCHEMAS = {
    "snapcraft project  (https://snapcraft.io)",
    "batect configuration file",
    "UI5 Tooling Configuration File (ui5.yaml)",
    "Renovate config file (https://github.com/renovatebot/renovate)",
    "Renovate config file (https://renovatebot.com/)",
    "Jenkins X Pipeline YAML configuration files",
    "TypeScript compiler configuration file",
    "JSON Schema for GraphQL Mesh config file",
    "Configuration file for stylelint",
    "Travis CI configuration file",
    "JSON schema for ESLint configuration files",
    "Ansible task files-2.0",
    "Ansible task files-2.1",
    "Ansible task files-2.2",
    "Ansible task files-2.3",
    "Ansible task files-2.4",
    "Ansible task files-2.5",
    "Ansible task files-2.6",
    "Ansible task files-2.7",
    "Ansible task files-2.9",
    "JSON Schema for GraphQL Code Generator config file",
    # oneOf on property names means only objects are valid, but it's a very
    # filter-heavy way to express that.  TODO: canonicalise oneOf to anyOf.
    "draft7/oneOf complex types",
}

with open(Path(__file__).parent / "corpus-schemastore-catalog.json") as f:
    catalog = json.load(f)
with open(Path(__file__).parent / "corpus-suite-schemas.json") as f:
    suite, invalid_suite = json.load(f)
with open(Path(__file__).parent / "corpus-reported.json") as f:
    reported = json.load(f)
    assert set(reported).isdisjoint(suite)
    suite.update(reported)


def to_name_params(corpus):
    for n in sorted(corpus):
        if n in INVALID_SCHEMAS | NON_EXISTENT_REF_SCHEMAS:
            continue
        if n in UNSUPPORTED_SCHEMAS:
            continue
        elif n in SLOW_SCHEMAS:
            yield pytest.param(n, marks=pytest.mark.skip)
        elif n in FLAKY_SCHEMAS:
            yield pytest.param(n, marks=pytest.mark.skip(strict=False))
        else:
            if isinstance(corpus[n], dict) and "$schema" in corpus[n]:
                jsonschema.validators.validator_for(corpus[n]).check_schema(corpus[n])
            yield n


@pytest.mark.parametrize("name", sorted(INVALID_SCHEMAS))
def test_invalid_schemas_are_invalid(name):
    with pytest.raises(Exception):
        jsonschema.validators.validator_for(catalog[name]).check_schema(catalog[name])


@pytest.mark.parametrize("name", sorted(NON_EXISTENT_REF_SCHEMAS))
def test_invalid_ref_schemas_are_invalid(name):
    with pytest.raises(Exception):
        resolve_all_refs(catalog[name])


RECURSIVE_REFS = {
    # From upstream validation test suite
    "draft4/valid definition",
    "draft4/remote ref, containing refs itself",
    "draft7/remote ref, containing refs itself",
    "draft7/root pointer ref",
    "draft7/valid definition",
    # Schema also requires draft 03, which hypothesis-jsonschema doesn't support
    "A JSON Schema for ninjs by the IPTC. News and publishing information. See https://iptc.org/standards/ninjs/-1.0",
    # From schemastore
    "A JSON schema for Open API documentation files",
    "Avro Schema Avsc file",
    "AWS CloudFormation provides a common language for you to describe and provision all the infrastructure resources in your cloud environment.",
    "JSON schema .NET template files",
    "AppVeyor CI configuration file",
    "JSON Document Transofrm",
    "JSON Linked Data files",
    "Meta-validation schema for JSON Schema Draft 4",
    "JSON schema for vim plugin addon-info.json metadata files",
    "Meta-validation schema for JSON Schema Draft 7",
    "Neotys as-code load test specification, more at: https://github.com/Neotys-Labs/neoload-cli",
    "Metadata spec v1.26.4 for KSP-CKAN",
    "Digital Signature Service Core Protocols, Elements, and Bindings Version 2.0",
    "Opctl schema for describing an op",
    "Metadata spec v1.27 for KSP-CKAN",
    "PocketMine plugin manifest file",
    "BuckleScript configuration file",
    "Schema for CircleCI 2.0 config files",
    "Source Map files version 3",
    "Schema for Minecraft Bukkit plugin description files",
    "Swagger API 2.0 schema",
    "Static Analysis Results Interchange Format (SARIF) version 1",
    "Static Analysis Results Format (SARIF), Version 2.1.0-rtm.4",
    "Static Analysis Results Interchange Format (SARIF) version 2",
    "Static Analysis Results Format (SARIF), Version 2.1.0-rtm.3",
    "Static Analysis Results Format (SARIF), Version 2.1.0-rtm.5",
    "Web component file",
    "Vega visualization specification file",
    "The AWS Serverless Application Model (AWS SAM, previously known as Project Flourish) extends AWS CloudFormation to provide a simplified way of defining the Amazon API Gateway APIs, AWS Lambda functions, and Amazon DynamoDB tables needed by your serverless application.",
    "Windows App localization file",
    "YAML schema for GitHub Workflow",
    "JSON-stat 2.0 Schema",
    "Vega-Lite visualization specification file",
    "Language grammar description files in Textmate and compatible editors",
    "JSON Schema for GraphQL Mesh Config gile-0.0.16",
    "Azure Pipelines YAML pipelines definition",
    "Action and rule configuration descriptor for Yippee-Ki-JSON transformations.-1.1.2",
    "Action and rule configuration descriptor for Yippee-Ki-JSON transformations.-latest",
    "Schema for Camel K YAML DSL",
}


def xfail_on_reference_resolve_error(f):
    @proxies(f)
    def inner(*args, **kwargs):
        _, name = args
        assert isinstance(name, str)
        try:
            f(*args, **kwargs)
            assert name not in RECURSIVE_REFS
        except jsonschema.exceptions.RefResolutionError as err:
            if (
                isinstance(err, HypothesisRefResolutionError)
                or isinstance(err._cause, HypothesisRefResolutionError)
            ) and (
                "does not fetch remote references" in str(err)
                or name in RECURSIVE_REFS
                and "Could not resolve recursive references" in str(err)
            ):
                pytest.xfail()
            raise

    return inner


@pytest.mark.parametrize("name", to_name_params(catalog))
@settings(deadline=None, max_examples=5, suppress_health_check=HealthCheck.all())
@given(data=st.data())
@xfail_on_reference_resolve_error
def test_can_generate_for_real_large_schema(data, name):
    note(name)
    value = data.draw(from_schema(catalog[name]))
    jsonschema.validate(value, catalog[name])


@pytest.mark.parametrize("name", to_name_params(suite))
@settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    deadline=None,
    max_examples=20,
)
@given(data=st.data())
@xfail_on_reference_resolve_error
def test_can_generate_for_test_suite_schema(data, name):
    note(suite[name])
    value = data.draw(from_schema(suite[name]))
    try:
        jsonschema.validate(value, suite[name])
    except jsonschema.exceptions.SchemaError:
        jsonschema.Draft4Validator(suite[name]).validate(value)


@pytest.mark.parametrize("name", to_name_params(invalid_suite))
def test_cannot_generate_for_empty_test_suite_schema(name):
    strat = from_schema(invalid_suite[name])
    with pytest.raises(Exception):
        strat.example()


# This schema has overlapping patternProperties - this is OK, so long as they're
# merged or otherwise handled correctly, with the exception of the key "ab" which
# would have to be both an integer and a string (and is thus disallowed).
OVERLAPPING_PATTERNS_SCHEMA = {
    "type": "string",
    "patternProperties": {
        r"\A[ab]{1,2}\Z": {},
        r"\Aa[ab]\Z": {"type": "integer"},
        r"\A[ab]b\Z": {"type": "string"},
    },
    "additionalProperties": False,
    "minimumProperties": 1,
}


@given(from_schema(OVERLAPPING_PATTERNS_SCHEMA))
def test_handles_overlapping_patternproperties(value):
    jsonschema.validate(value, OVERLAPPING_PATTERNS_SCHEMA)
    assert "ab" not in value


# A dictionary with zero or one keys, which was always empty due to a bug.
SCHEMA = {
    "type": "object",
    "properties": {"key": {"type": "string"}},
    "additionalProperties": False,
}


@given(from_schema(SCHEMA))
def test_single_property_can_generate_nonempty(query):
    # See https://github.com/Zac-HD/hypothesis-jsonschema/issues/25
    assume(query)


@given(rfc3339("date-time"))
def test_generated_rfc3339_datetime_strings_are_valid(datetime_string):
    assert strict_rfc3339.validate_rfc3339(datetime_string)


UNIQUE_NUMERIC_ARRAY_SCHEMA = {
    "type": "array",
    "uniqueItems": True,
    "items": {"enum": [0, 0.0]},
    "minItems": 1,
}


@given(from_schema(UNIQUE_NUMERIC_ARRAY_SCHEMA))
def test_numeric_uniqueness(value):
    # NOTE: this kind of test should usually be embedded in corpus-reported.json,
    # but in this case the type of the enum elements matter and we don't want to
    # allow a flexible JSON loader to mess things up.
    jsonschema.validate(value, UNIQUE_NUMERIC_ARRAY_SCHEMA)


def test_draft03_not_supported():
    # Also checks that errors are deferred from importtime to runtime
    @given(from_schema({"$schema": "http://json-schema.org/draft-03/schema#"}))
    def f(_):
        raise AssertionError

    with pytest.raises(InvalidArgument):
        f()


@pytest.mark.parametrize("type_", ["integer", "number"])
def test_impossible_multiplier(type_):
    # Covering test for a failsafe branch, which explicitly returns nothing()
    # if scaling the bounds and taking their ceil/floor also inverts them.
    schema = {"maximum": -1, "minimum": -1, "multipleOf": 0.0009765625000000002}
    schema["type"] = type_
    strategy = from_schema(schema)
    strategy.validate()
    assert strategy.is_empty


ALLOF_CONTAINS = {
    "type": "array",
    "items": {"type": "string"},
    "allOf": [{"contains": {"const": "A"}}, {"contains": {"const": "B"}}],
}


@pytest.mark.xfail(raises=FailedHealthCheck)
@given(from_schema(ALLOF_CONTAINS))
def test_multiple_contains_behind_allof(value):
    # By placing *multiple* contains elements behind "allOf" we've disabled the
    # mixed-generation logic, and so we can't generate any valid instances at all.
    jsonschema.validate(value, ALLOF_CONTAINS)


@jsonschema.FormatChecker.cls_checks("card-test")
def validate_card_format(string):
    # For the real thing, you'd want use the Luhn algorithm; this is enough for tests.
    return bool(re.match(r"^\d{4} \d{4} \d{4} \d{4}$", string))


@pytest.mark.parametrize(
    "kw",
    [
        {"foo": "not a strategy"},
        {5: st.just("name is not a string")},
        {"full-date": st.just("2000-01-01")},  # can't override a standard format
        {"card-test": st.just("not a valid card")},
    ],
)
@given(data=st.data())
def test_custom_formats_validation(data, kw):
    s = from_schema({"type": "string", "format": "card-test"}, custom_formats=kw)
    with pytest.raises(InvalidArgument):
        data.draw(s)


@given(
    num=from_schema(
        {"type": "string", "format": "card-test"},
        custom_formats={"card-test": st.just("4111 1111 1111 1111")},
    )
)
def test_allowed_custom_format(num):
    assert num == "4111 1111 1111 1111"


@given(
    string=from_schema(
        {"type": "string", "format": "not registered"},
        custom_formats={"not registered": st.just("hello world")},
    )
)
def test_allowed_unknown_custom_format(string):
    assert string == "hello world"
    assert "not registered" not in jsonschema.FormatChecker().checkers
