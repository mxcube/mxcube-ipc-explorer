"""Turns a method's argument JSON schema (from mxcubecore.ipc's
`_debug_describe_role` - see IPC_FORMAT.md section 7) into an editable
kwargs template, for pre-filling the call form's kwargs field. Validating
a filled-in kwargs dict against that same schema (client-side, before
sending) is just `jsonschema.validate()` directly - see app.py's Call
handler.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_EXAMPLE_BY_TYPE = {
    "string": "",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _example_for_property(prop_schema: Dict[str, Any]) -> Any:
    if "default" in prop_schema:
        return prop_schema["default"]

    schema_type = prop_schema.get("type")
    if schema_type is None:
        # e.g. Optional[float] -> {"anyOf": [{"type": "number"}, {"type": "null"}]}
        for variant in (*prop_schema.get("anyOf", ()), *prop_schema.get("oneOf", ())):
            if variant.get("type") not in (None, "null"):
                schema_type = variant.get("type")
                break

    return _EXAMPLE_BY_TYPE.get(schema_type)


def kwargs_template(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An editable {field: example value} dict matching <schema>'s
    top-level properties - each field's own "default" if it has one,
    otherwise a placeholder matching its type. Empty dict if <schema> is
    falsy or has no properties (e.g. a no-argument method).
    """
    if not schema:
        return {}
    return {
        name: _example_for_property(prop)
        for name, prop in schema.get("properties", {}).items()
    }
