"""Every JSON request body refuses keys it does not declare (Lukas, 2026-10-03).

Checked on the OpenAPI schema the app publishes, so a new request model that forgets to
inherit `RequestModel` fails here before it ships, and the three bodies that are plain
dicts are named with the reason each is checked at runtime instead.
"""

from anki_api.app import create_app
from anki_api.config import Settings

# Bodies typed `dict[str, Any]`, validated by the handler instead of the model:
DICT_BODIES = {
    ("put", "/v1/preferences"),             # ParseDict into the Preferences proto -> 422 invalid_body
    ("put", "/v1/stats/graph-preferences"),  # ParseDict into GraphPreferences -> 422 invalid_body
    ("put", "/v1/deck-presets/{preset_id}"),  # _deep_merge 422s a key the preset does not have
}


def _schema(spec: dict, node: dict) -> dict:
    if "$ref" in node:
        return spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
    return node


def _object_schemas(spec: dict, node: dict, seen: set[str]) -> list[tuple[str, dict]]:
    """`node` and every object schema reachable from it (nested models, list items)."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[1]
        if name in seen:
            return []
        seen.add(name)
        node = spec["components"]["schemas"][name]
    else:
        name = node.get("title", "?")
    # a MODEL declares `properties`; a free-form map like `fields: dict[str, str]` is an
    # object whose `additionalProperties` is the value schema, and is open by design
    out = [(name, node)] if "properties" in node else []
    for child in list(node.get("properties", {}).values()) + [node.get("items")] + node.get("anyOf", []):
        if child:
            out += _object_schemas(spec, child, seen)
    return out


def test_every_json_request_body_forbids_unknown_keys():
    spec = create_app(Settings(collection_path="/nonexistent/collection.anki2")).openapi()
    json_bodies = 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody")
            if not body or "application/json" not in body["content"]:
                continue
            json_bodies += 1
            root = body["content"]["application/json"]["schema"]
            if (method, path) in DICT_BODIES:
                assert "$ref" not in root, f"{method.upper()} {path} is listed as a dict body but has a model"
                continue
            schemas = _object_schemas(spec, root, set())
            assert schemas, f"{method.upper()} {path} has no object schema: {root}"
            for name, schema in schemas:
                assert schema.get("additionalProperties") is False, \
                    f"{method.upper()} {path}: {name} accepts unknown keys"
    assert json_bodies >= 60  # the walk saw the API, not an empty spec
