#!/usr/bin/env python3
"""Validate amber-manifest.json5 against Amber's config_schema profile.

Mirrors the rules enforced by RDI-Foundation/amber's compiler in
`compiler/manifest/src/config_schema_profile.rs`. Catches issues
locally that would otherwise only surface as a `manifest::validation_error`
during AgentBeats Quick Submit's compile step.

The full Amber profile is implemented as a JSON-Schema meta-schema; we
re-encode the rules that bit us in past iterations (and the documented
ones from the source) as direct checks. Exit 0 if valid, 1 otherwise.

Run from the repo root:

    python scripts/validate-manifest.py
    # or specify a path:
    python scripts/validate-manifest.py path/to/manifest.json5
"""

from __future__ import annotations

import json5
import re
import sys
from pathlib import Path

# Source: compiler/manifest/src/config_schema_profile.rs
KEY_NAME_RE = re.compile(r"^(?!.*__)[a-z][a-z0-9_]*$")

BANNED_KEYWORDS = {
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "patternProperties",
    "propertyNames",
    "dependentSchemas",
    "dependentRequired",
    "unevaluatedProperties",
    "unevaluatedItems",
    "$dynamicRef",
    "$recursiveRef",
}


def _walk_banned(node: object, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in BANNED_KEYWORDS:
                errors.append(
                    f"{path}.{key}: uses JSON Schema keyword `{key}`, "
                    f"which Amber's profile bans"
                )
            _walk_banned(value, f"{path}.{key}", errors)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_banned(item, f"{path}[{i}]", errors)


def validate_config_schema(schema: dict) -> list[str]:
    errors: list[str] = []

    if not isinstance(schema, dict):
        return [f"config_schema must be an object, got {type(schema).__name__}"]

    type_value = schema.get("type")
    has_props = "properties" in schema
    has_required = "required" in schema
    if (has_props or has_required) and type_value not in ("object", ["object"]):
        if not (isinstance(type_value, list) and "object" in type_value):
            errors.append(
                "config_schema.type must include 'object' when properties or "
                f"required are declared (got {type_value!r})"
            )

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append(f"config_schema.properties must be a dict, got {type(properties).__name__}")
        properties = {}

    for key in properties:
        if not KEY_NAME_RE.match(key):
            errors.append(
                f"config_schema.properties[{key!r}]: name fails regex "
                f"{KEY_NAME_RE.pattern} — must be lowercase snake_case, "
                "no double underscores, no leading digit. Amber's profile "
                "rejects uppercase names. Map to UPPERCASE env vars in "
                "program.env via ${config.<lower>}."
            )

    for key, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        if "default" in prop:
            errors.append(
                f"config_schema.properties[{key!r}]: has `default` — Amber "
                "profile rejects defaults. Mark the property required and "
                "let the user paste an empty string for unused fields."
            )

    required = schema.get("required", [])
    if not isinstance(required, list):
        errors.append(f"config_schema.required must be a list, got {type(required).__name__}")
        required = []

    missing_required = [k for k in properties if k not in required]
    if missing_required:
        errors.append(
            f"config_schema: properties not in `required`: {missing_required}. "
            "The Amber profile only accepts schemas where every declared "
            "property is required."
        )

    extra_required = [k for k in required if k not in properties]
    if extra_required:
        errors.append(
            f"config_schema.required: lists names not declared in properties: "
            f"{extra_required}"
        )

    for key in required:
        if not isinstance(key, str) or not KEY_NAME_RE.match(key):
            errors.append(
                f"config_schema.required: entry {key!r} fails name regex "
                f"{KEY_NAME_RE.pattern}"
            )

    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, bool):
        errors.append(
            f"config_schema.additionalProperties must be boolean, got "
            f"{type(additional).__name__} ({additional!r}). Amber profile "
            "does not support sub-schema form."
        )

    _walk_banned(schema, "config_schema", errors)

    return errors


def validate_program_env(program: dict, schema_keys: set[str]) -> list[str]:
    """Sanity-check that every `${config.X}` referenced in env exists in config_schema."""
    errors: list[str] = []
    if not isinstance(program, dict):
        return errors
    env = program.get("env", {})
    if not isinstance(env, dict):
        return errors

    ref_re = re.compile(r"\$\{config\.([^}]+)\}")
    for env_var, value in env.items():
        if not isinstance(value, str):
            continue
        for match in ref_re.finditer(value):
            referenced = match.group(1)
            if referenced not in schema_keys:
                errors.append(
                    f"program.env.{env_var}: references ${{config.{referenced}}} "
                    f"but that key is not declared in config_schema.properties "
                    f"(declared: {sorted(schema_keys)})"
                )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        manifest_path = Path(argv[1])
    else:
        manifest_path = Path(__file__).parent.parent / "amber-manifest.json5"

    if not manifest_path.exists():
        print(f"error: manifest not found at {manifest_path}", file=sys.stderr)
        return 2

    with manifest_path.open() as f:
        manifest = json5.load(f)

    if not isinstance(manifest, dict):
        print("error: manifest root must be an object", file=sys.stderr)
        return 2

    errors: list[str] = []

    schema = manifest.get("config_schema")
    schema_keys: set[str] = set()
    if schema is None:
        print(f"note: {manifest_path} has no config_schema; nothing to check there")
    else:
        errors.extend(validate_config_schema(schema))
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            schema_keys = set(schema["properties"].keys())

    program = manifest.get("program", {})
    errors.extend(validate_program_env(program, schema_keys))

    if errors:
        print(f"❌ {manifest_path} failed Amber profile validation:\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"✓ {manifest_path} passes Amber config_schema profile checks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
