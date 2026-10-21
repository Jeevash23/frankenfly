"""Generate frontend/src/api.gen.ts: TypeScript types for the State the server publishes (GET /api/schema/state)
and for the request and response models in /api/openapi.json.

    python3 scripts/gen_types.py                 # write the file
    python3 scripts/gen_types.py --check         # exit 1 when the file is stale (CI runs this)
    python3 scripts/gen_types.py --url http://127.0.0.1:8000   # read the schemas from a running server

Standard library only. Without --url the schemas come from the backend code, through backend/.venv's Python when
it exists. State types say what the server sends: every field present unless marked optional. A model that a
request may send with fields left out (the server fills in defaults) gets an "Input" variant where it differs.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend/src/api.gen.ts"
WIDTH = 100  # frontend/.prettierrc printWidth, so the output is already formatted
# FastAPI's default validation error schemas; this server answers {"detail": [{location, message, type}]}.
SKIP = {"HTTPValidationError", "ValidationError"}
DUMP = """import json, sys
sys.path.insert(0, "backend/src")
from digitalfly.api.models import RunConfig, state_schema
from digitalfly.main import create_app
app = create_app(RunConfig(engine="toy"), render=False)
with open(sys.argv[1], "w") as output:
    json.dump({"openapi": app.openapi(), "state": state_schema()}, output)
"""


def schemas(url: str | None) -> tuple[dict, dict]:
    if url:
        def get(path):
            with urlopen(url.rstrip("/") + path, timeout=30) as response:
                return json.load(response)
        return get("/api/openapi.json"), get("/api/schema/state")
    venv = ROOT / "backend/.venv/bin/python"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "schemas.json"
        done = subprocess.run([str(venv) if venv.is_file() else sys.executable, "-c", DUMP, str(path)], cwd=ROOT,
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            sys.exit(f"Could not read the schemas from the backend (set it up with ./scripts/setup.sh, or pass --url "
                     f"with the app running):\n{done.stderr}")
        data = json.loads(path.read_text())
    return data["openapi"], data["state"]


def quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) else quote(name)


def literal(value) -> str:
    if isinstance(value, str):
        return quote(value)
    return "null" if value is None else json.dumps(value)


def top_level(text: str, separator: str) -> list[str]:
    """`text` split at `separator` outside brackets and quotes."""
    parts, depth, start, quoted, i = [], 0, 0, False, 0
    while i < len(text):
        char = text[i]
        if quoted:
            quoted = char != "'"
            i += 2 if char == "\\" else 1
            continue
        if char == "'":
            quoted = True
        elif char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth -= 1
        elif depth == 0 and text.startswith(separator, i):
            parts.append(text[start:i])
            start = i + len(separator)
            i = start
            continue
        i += 1
    return parts + [text[start:]]


def shape(schema):
    """The parts of a schema that its TypeScript depends on; references by name only."""
    if isinstance(schema, list):
        return [shape(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for name, value in schema.items():
        if name == "properties":
            out[name] = {field: shape(item) for field, item in value.items()}
            out["required"] = sorted(schema.get("required", []))
        elif name == "$ref":
            out[name] = value.rsplit("/", 1)[-1]
        elif name in {"const", "enum", "anyOf", "oneOf", "allOf", "type", "items", "prefixItems",
                      "additionalProperties", "description"}:
            out[name] = shape(value)
    return out


def references(schema) -> set[str]:
    if isinstance(schema, list):
        return set().union(*map(references, schema)) if schema else set()
    if not isinstance(schema, dict):
        return set()
    found = {schema["$ref"].rsplit("/", 1)[-1]} if "$ref" in schema else set()
    return found.union(*(references(value) for value in schema.values()))


class Generator:
    def __init__(self, openapi: dict, state: dict):
        state = dict(state)
        self.sent = {**state.pop("$defs", {}), "State": state}
        self.request = {name: schema for name, schema in openapi.get("components", {}).get("schemas", {}).items()
                        if name not in SKIP}
        self.openapi = openapi
        # One type serves both when it reads the same, references included; otherwise the request model is the
        # "Input" variant (fields with server defaults optional).
        shared = {name for name, schema in self.request.items()
                  if name in self.sent and shape(schema) == shape(self.sent[name])}
        while unshared := {name for name in shared if not references(self.request[name]) <= shared}:
            shared -= unshared
        self.shared = shared
        self.names = {"sent": {name: name for name in self.sent},
                      "request": {name: re.sub(r"\W", "", name) + ("Input" if name in self.sent.keys() - shared else "")
                                  for name in self.request}}

    def type(self, schema: dict, space: str) -> str:
        if "$ref" in schema:
            return self.names[space][schema["$ref"].rsplit("/", 1)[-1]]
        if "const" in schema:
            return literal(schema["const"])
        if "enum" in schema:
            return self.union([literal(v) for v in schema["enum"]])
        for word in ("anyOf", "oneOf"):
            if word in schema:
                return self.union([self.type(option, space) for option in schema[word]])
        if "allOf" in schema and len(schema["allOf"]) == 1:
            return self.type(schema["allOf"][0], space)
        kind = schema.get("type")
        if isinstance(kind, list):
            return self.union([self.type({**schema, "type": k}, space) for k in kind])
        if kind == "string":
            return "string"
        if kind in ("integer", "number"):
            return "number"
        if kind in ("boolean", "null"):
            return kind
        if kind == "array":
            if "prefixItems" in schema:
                return "[" + ", ".join(self.type(item, space) for item in schema["prefixItems"]) + "]"
            item = self.type(schema.get("items", {}), space)
            return (f"({item})" if len(top_level(item, " | ")) > 1 else item) + "[]"
        if kind == "object" or "properties" in schema:
            if schema.get("properties"):
                required = set(schema.get("required", []))
                return "{" + "; ".join(f"{key(name)}{'' if name in required else '?'}: {self.type(value, space)}"
                                       for name, value in schema["properties"].items()) + "}"
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict):
                return f"Record<string, {self.type(extra, space)}>"
            return "Record<string, never>" if extra is False else "Record<string, unknown>"
        return "unknown"

    @staticmethod
    def union(options: list[str]) -> str:
        return " | ".join(dict.fromkeys(options))

    @staticmethod
    def member(indent: str, head: str, value: str, end: str = ";") -> list[str]:
        """`head value;` in Prettier's layout: one line when it fits, otherwise one union option per line."""
        line = f"{indent}{head} {value}{end}"
        options = top_level(value, " | ")
        if len(line) <= WIDTH:
            return [line]
        if len(options) > 1:
            return [f"{indent}{head}"] + [f"{indent}  | {option}" for option in options[:-1]] + \
                [f"{indent}  | {options[-1]}{end}"]
        inner = re.fullmatch(r"\((.*)\)\[\]", value)
        if inner and len(top_level(inner.group(1), " | ")) > 1:
            return [f"{indent}{head} ("] + [f"{indent}  | {option}" for option in top_level(inner.group(1), " | ")] + \
                [f"{indent})[]{end}"]
        return [line]

    @staticmethod
    def comment(text: str | None, indent: str = "") -> list[str]:
        if not text:
            return []
        lines = text.strip().splitlines()
        if len(lines) == 1 and len(indent) + len(lines[0]) + 7 <= WIDTH:
            return [f"{indent}/** {lines[0]} */"]
        return [f"{indent}/**"] + [f"{indent} * {line}".rstrip() for line in lines] + [f"{indent} */"]

    def declaration(self, name: str, schema: dict, space: str) -> list[str]:
        lines = self.comment(schema.get("description"))
        properties = schema.get("properties")
        if schema.get("type") != "object" or not properties:
            return lines + self.member("", f"export type {name} =", self.type(schema, space))
        required = set(schema.get("required", []))
        lines.append(f"export interface {name} {{")
        for field, value in properties.items():
            lines += self.member("  ", f"{key(field)}{'' if field in required else '?'}:", self.type(value, space))
        return lines + ["}"]

    def endpoints(self, title: str, entries: list[tuple[str, str]]) -> list[str]:
        if not entries:
            return [f"export interface {title} {{}}"]
        lines = [f"export interface {title} {{"]
        for name, value in entries:
            lines += self.member("  ", f"{quote(name)}:", value)
        return lines + ["}"]

    def render(self) -> str:
        out = ["// generated by scripts/gen_types.py — do not edit",
               "// Run `backend/.venv/bin/python scripts/gen_types.py` after changing the API models.", "",
               "// What the server sends: State over /api/ws and /api/status (GET /api/schema/state).", ""]
        for name in ["State"] + sorted(set(self.sent) - {"State"}):
            out += self.declaration(name, self.sent[name], "sent") + [""]
        out += ["// Request bodies and documented responses (/api/openapi.json).", ""]
        for name in sorted(set(self.request) - self.shared, key=lambda n: self.names["request"][n]):
            out += self.declaration(self.names["request"][name], self.request[name], "request") + [""]
        bodies, responses = [], []
        for path, operations in sorted(self.openapi.get("paths", {}).items()):
            for method, operation in operations.items():
                body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
                if body:
                    bodies.append((f"{method.upper()} {path}", self.type(body, "request")))
                answer = operation.get("responses", {}).get("200", {}).get("content", {}).get(
                    "application/json", {}).get("schema", {})
                if "$ref" in answer:
                    responses.append((f"{method.upper()} {path}", self.type(answer, "request")))
        out += ["/** The JSON body each command takes. */"] + self.endpoints("RequestBodies", bodies) + [""]
        out += ["/** Responses with a documented shape. */"] + self.endpoints("Responses", responses)
        return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if frontend/src/api.gen.ts is stale")
    parser.add_argument("--url", help="read the schemas from this running server instead of the backend code")
    args = parser.parse_args()
    text = Generator(*schemas(args.url)).render()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text() != text:
            sys.exit(f"{OUTPUT.relative_to(ROOT)} is stale: run backend/.venv/bin/python scripts/gen_types.py")
        print(f"{OUTPUT.relative_to(ROOT)} is up to date.")
        return
    OUTPUT.write_text(text)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
