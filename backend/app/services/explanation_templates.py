"""Per-rule explanation templates: the offline explanation path.

One template per rule ID. Each builds its prose *and* a concrete before/after
from the finding's own metadata, so the output names the real file, the real
line and the real code. A template that said "use environment variables"
without showing the edit would be worth less than nothing — the user already
knows the rule's title.

This is what makes MergeX work with no API key. The language model improves
the wording; it does not enable the feature.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Final

from app.analysis.findings import Finding
from app.services.explanations import Explanation

__all__ = ["render_template"]

SOURCE: Final[str] = "template"


def render_template(finding: Finding) -> Explanation:
    """Build an explanation for a finding without a language model."""
    builder = _TEMPLATES.get(finding.rule_id, _generic)
    explanation, fix, before, after = builder(finding)
    return Explanation(
        fingerprint=finding.fingerprint,
        explanation=explanation.strip(),
        suggested_fix=fix.strip(),
        source=SOURCE,
        fix_before=before or None,
        fix_after=after or None,
    )


Rendered = tuple[str, str, str, str]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _at(finding: Finding) -> str:
    """``frontend/src/api/users.ts:7``, for referring to the real location."""
    return str(finding.primary_location)


def _first_evidence_line(finding: Finding) -> str:
    lines = [line for line in finding.evidence.splitlines() if line.strip()]
    return lines[0].strip() if lines else ""


def _is_python(path: str) -> bool:
    return PurePosixPath(path).suffix in {".py", ".pyi"}


def _corrected_raw_path(raw_path: str, called: str, suggested: str) -> str:
    """Rewrite a written path so it matches the route that exists.

    Normalisation preserves segment count, so the written path's segments line
    up with the normalised ones. Only the segments that differ *and* are not
    parameters are replaced, which keeps `${id}` interpolations intact.
    """
    raw_segments = raw_path.split("/")
    called_segments = called.strip("/").split("/")
    suggested_segments = suggested.strip("/").split("/")
    if len(called_segments) != len(suggested_segments):
        return suggested

    # Align the normalised segments against the non-empty written ones.
    indices = [index for index, segment in enumerate(raw_segments) if segment]
    if len(indices) != len(called_segments):
        return suggested

    for position, index in enumerate(indices):
        if called_segments[position] == suggested_segments[position]:
            continue
        if suggested_segments[position] == "{}":
            continue
        raw_segments[index] = suggested_segments[position]
    return "/".join(raw_segments)


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def _api_001(finding: Finding) -> Rendered:
    metadata = finding.metadata
    method = metadata.get("method", "GET")
    path = metadata.get("path", "")
    caller = metadata.get("caller")
    nearby = metadata.get("nearby_routes") or []

    explanation = (
        f"{caller or 'This call'} requests {method} {path}, and no route in the backend "
        f"serves that path. At runtime the request returns 404 and the feature fails. "
        f"Neither the TypeScript compiler nor a linter can see across the layer "
        f"boundary, so this passes review and CI."
    )
    if nearby:
        explanation += f" Routes that do exist under the same prefix: {', '.join(nearby[:4])}."

    fix = (
        f"Either add a {method} {path} route to the backend, or change the call at "
        f"{_at(finding)} to an endpoint that exists."
    )
    before = _first_evidence_line(finding)
    after = (
        f'@router.{method.lower()}("{path}")\n'
        f"def {_handler_name_for(path)}():\n"
        f"    ...  # implement, or remove the frontend call instead"
    )
    return (explanation, fix, before, after)


def _handler_name_for(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part and part != "{}"]
    return "_".join(parts).replace("-", "_") or "handler"


def _api_002(finding: Finding) -> Rendered:
    metadata = finding.metadata
    called = metadata.get("called_path", "")
    suggested = metadata.get("suggested_path", "")
    raw_path = metadata.get("raw_path", called)
    method = metadata.get("method", "GET")

    explanation = (
        f"The call asks for {method} {called}, but the backend serves "
        f"{method} {suggested} — the two differ by a single character. The request "
        f"returns 404, and because the path reads almost correctly this is easy to "
        f"miss in review."
    )
    corrected = _corrected_raw_path(raw_path, called, suggested)
    fix = (
        f"At {_at(finding)}, change the request path from {raw_path!r} to "
        f"{corrected!r} to match {metadata.get('handler', 'the existing route')}."
    )
    before = _first_evidence_line(finding)
    after = before.replace(raw_path, corrected) if raw_path and raw_path in before else ""
    return (explanation, fix, before, after)


def _api_003(finding: Finding) -> Rendered:
    metadata = finding.metadata
    call_method = metadata.get("call_method", "")
    route_methods = metadata.get("route_methods") or []
    path = metadata.get("path", "")
    expected = route_methods[0] if route_methods else "the declared method"

    explanation = (
        f"The frontend sends {call_method} to {path}, but the backend declares that "
        f"path for {', '.join(route_methods) or 'another method'} only. The server "
        f"replies 405 Method Not Allowed. The path itself is correct, which is why "
        f"this survives a read-through."
    )
    fix = (
        f"At {_at(finding)}, change the request method from {call_method} to "
        f"{expected}, or add a {call_method} handler for {path}."
    )
    before = _first_evidence_line(finding)
    after = ""
    if before and call_method:
        after = before.replace(f".{call_method.lower()}(", f".{expected.lower()}(")
    if not after or after == before:
        # The verb was not where the simple replacement expected it. Show the
        # corrected call rather than leaving the user with no `after` at all.
        after = f'await api.{expected.lower()}("{path}");'
    return (explanation, fix, before, after)


def _api_004(finding: Finding) -> Rendered:
    metadata = finding.metadata
    drifted = metadata.get("drifted_fields") or []
    model = metadata.get("model", "the request model")
    pairs = ", ".join(f"{item['sent']} → {item['expected']}" for item in drifted)

    explanation = (
        f"The request body sends {_plural(len(drifted), 'a field')} the backend does "
        f"not accept: {pairs}. {model} declares the snake_case spelling, so Pydantic "
        f"rejects the request as missing a required field — or drops the value "
        f"silently if the field is optional. The frontend's own types are "
        f"self-consistent, so nothing local catches it."
    )
    fix = (
        f"At {_at(finding)}, rename the payload {_plural(len(drifted), 'key')} to match "
        f"{model}: {pairs}. Alternatively add an alias on the model if the camelCase "
        f"name is intended as the public contract."
    )
    before = _first_evidence_line(finding)
    after = before
    for item in drifted:
        after = after.replace(item["sent"], f"{item['expected']}: {item['sent']}")
    if after == before:
        # The payload was not written inline on this line; show the shape the
        # body must take instead of leaving the `after` empty.
        renamed = ", ".join(f"{item['expected']}: {item['sent']}" for item in drifted)
        after = f"{{ {renamed} }}"
    return (explanation, fix, before, after)


def _api_005(finding: Finding) -> Rendered:
    metadata = finding.metadata
    dependencies = metadata.get("dependencies") or []
    handler = metadata.get("handler", "the route")

    guard = ", ".join(dependencies) or "an authentication dependency"
    explanation = (
        f"{handler} is protected by {guard}, but this request attaches no credentials "
        f"and the client sets no default Authorization header. Every call returns 401, "
        f"so the feature never works for anyone."
    )
    fix = (
        f"At {_at(finding)}, attach the token — either on this request or, better, as "
        f"a default header or request interceptor on the shared client so every call "
        f"to a protected route carries it."
    )
    before = _first_evidence_line(finding)
    after = (
        "// on the shared client, once:\n"
        "api.interceptors.request.use((config) => {\n"
        "  config.headers.Authorization = `Bearer ${getToken()}`;\n"
        "  return config;\n"
        "});"
    )
    return (explanation, fix, before, after)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _db_001(finding: Finding) -> Rendered:
    metadata = finding.metadata
    table = metadata.get("table", "")
    column = metadata.get("column", "")
    model = metadata.get("model", "the model")
    field_name = metadata.get("field", column)
    column_type = metadata.get("expected_type") or "TEXT"

    explanation = (
        f"{model}.{field_name} maps {table}.{column}, but no migration ever creates "
        f"that column. The ORM names every mapped column in its SELECT list, so this "
        f"breaks reads of {table} as well as writes — the first query against the "
        f"table raises UndefinedColumn."
    )
    fix = (
        f"Add a migration creating {table}.{column}, or remove the field from {model} "
        f"at {_at(finding)} if it is no longer wanted."
    )
    before = _first_evidence_line(finding)
    after = (
        f"-- new migration\n"
        f"ALTER TABLE {table} ADD COLUMN {column} {_sql_type_for(column_type)};"
    )
    return (explanation, fix, before, after)


def _sql_type_for(orm_type: str | None) -> str:
    mapping = {
        "String": "VARCHAR(255)",
        "Text": "TEXT",
        "Integer": "INTEGER",
        "BigInteger": "BIGINT",
        "Numeric": "NUMERIC(10, 2)",
        "Float": "DOUBLE PRECISION",
        "Boolean": "BOOLEAN",
        "DateTime": "TIMESTAMPTZ",
        "Date": "DATE",
        "JSON": "JSONB",
        "Uuid": "UUID",
    }
    return mapping.get(orm_type or "", "TEXT")


def _db_002(finding: Finding) -> Rendered:
    metadata = finding.metadata
    table = metadata.get("table", "")
    column = metadata.get("column", "")
    model_type = metadata.get("model_type", "")
    database_type = metadata.get("database_type", "")
    model_family = metadata.get("model_family", "")
    database_family = metadata.get("database_family", "")

    consequence = (
        "Money loses its fractional part on every write, silently — no error is "
        "raised, the values are simply wrong."
        if (model_family, database_family) == ("decimal", "integer")
        else "The two sides coerce differently, so values change as they cross the boundary."
    )
    explanation = (
        f"The model declares {table}.{column} as {model_type} ({model_family}) while "
        f"the database has {database_type} ({database_family}). {consequence}"
    )
    fix = (
        f"Decide which side is right. If the model is, add a migration altering the "
        f"column; if the database is, change the declaration at {_at(finding)}."
    )
    before = f"{column} {database_type}  -- in the migration"
    after = (
        f"-- new migration\n"
        f"ALTER TABLE {table} ALTER COLUMN {column} "
        f"TYPE {_sql_type_for(model_type.split('(')[0] if model_type else None)};"
    )
    return (explanation, fix, before, after)


def _db_003(finding: Finding) -> Rendered:
    metadata = finding.metadata
    table = metadata.get("table", "")
    column = metadata.get("column", "")
    existing = metadata.get("existing_columns") or []

    explanation = (
        f"This query reads {table}.{column}, which exists in neither the migrations "
        f"nor any ORM model. Raw SQL bypasses every check the ORM would have made, so "
        f"nothing catches it until the query runs and the database raises "
        f"UndefinedColumn. The columns {table} actually has are: "
        f"{', '.join(existing[:8]) or 'none found'}."
    )
    fix = (
        f"At {_at(finding)}, either correct the column name to one that exists, or add "
        f"a migration creating {table}.{column}."
    )
    before = _first_evidence_line(finding)
    after = (
        f"-- if the column is genuinely needed\n"
        f"ALTER TABLE {table} ADD COLUMN {column} TIMESTAMPTZ;"
    )
    return (explanation, fix, before, after)


def _db_004(finding: Finding) -> Rendered:
    metadata = finding.metadata
    table = metadata.get("table", "")
    column = metadata.get("column", "")
    references = metadata.get("references") or ""
    target_table = references.split(".")[0] if references else "the parent table"
    target_column = references.split(".")[1] if "." in references else "id"

    explanation = (
        f"The model declares {column} as a foreign key to {references}, but the "
        f"migration creates it as a plain column with no REFERENCES clause. The "
        f"database therefore cannot enforce the reference: rows in {table} can point "
        f"at {target_table} rows that do not exist, and any ON DELETE behaviour the "
        f"model implies does nothing."
    )
    fix = "Add the constraint in a migration so the database enforces what the model assumes."
    before = f"{column} INTEGER  -- no REFERENCES"
    after = (
        f"-- new migration\n"
        f"ALTER TABLE {table}\n"
        f"  ADD CONSTRAINT fk_{table}_{column}\n"
        f"  FOREIGN KEY ({column}) REFERENCES {target_table}({target_column});"
    )
    return (explanation, fix, before, after)


def _db_005(finding: Finding) -> Rendered:
    metadata = finding.metadata
    table = metadata.get("table", "")
    column = metadata.get("column", "")

    explanation = (
        f"{table}.{column} is used as a foreign key but has no index. Every join "
        f"through it, and every cascade check, is a sequential scan over {table}. "
        f"This is invisible on a small table and becomes the slowest query in the "
        f"application as the table grows."
    )
    fix = f"Add an index on {table}.{column} in a migration."
    before = f"-- no index on {table}.{column}"
    after = f"CREATE INDEX ix_{table}_{column} ON {table} ({column});"
    return (explanation, fix, before, after)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def _sec_001(finding: Finding) -> Rendered:
    metadata = finding.metadata
    variable = metadata.get("variable") or "this value"
    in_frontend = bool(metadata.get("in_frontend_bundle"))
    path = finding.primary_location.file_path

    exposure = (
        " Because this file is part of the frontend bundle, the credential is served "
        "to every visitor and readable in the browser's developer tools."
        if in_frontend
        else ""
    )
    explanation = (
        f"{variable} is a credential committed in source. Everyone with repository "
        f"access has it, and git history retains it after deletion — so removing the "
        f"line is not sufficient, the credential has to be rotated.{exposure}"
    )
    fix = (
        f"Rotate the credential at the provider first, then read it from the "
        f"environment at {_at(finding)} and remove the literal."
    )
    before = _first_evidence_line(finding)
    if in_frontend:
        after = (
            f"// Never ship a secret to the browser. Move the call to the backend and\n"
            f"// keep the credential there; expose only a public value if one is needed:\n"
            f"const {variable} = import.meta.env.VITE_PUBLIC_VALUE;"
        )
    elif _is_python(path):
        after = f'import os\n\n{variable} = os.environ["{variable}"]  # fails loudly if unset'
    else:
        after = f"const {variable} = process.env.{variable};"
    return (explanation, fix, before, after)


def _sec_002(finding: Finding) -> Rendered:
    metadata = finding.metadata
    handler = metadata.get("handler", "this route")
    method = metadata.get("method", "")
    path = metadata.get("path", "")
    terms = metadata.get("sensitive_terms") or []
    siblings = metadata.get("protected_siblings") or []
    dependencies = metadata.get("sibling_dependencies") or []
    dependency = dependencies[0] if dependencies else "require_user"

    explanation = (
        f"{handler} ({method} {path}) has no authentication dependency, while "
        f"{', '.join(siblings[:3]) or 'its siblings'} on the same router do. The path "
        f"or handler names {', '.join(terms)}, so this is a sensitive operation left "
        f"open — anyone who can reach the service can call it. The inconsistency with "
        f"its neighbours is what makes this an oversight rather than a deliberate "
        f"public endpoint."
    )
    fix = (
        f"Add the same dependency its siblings use to {handler} at {_at(finding)}, or "
        f"apply it to the whole router if every route should require it."
    )
    before = _first_evidence_line(finding)
    after = (
        f'@router.{method.lower() if method else "post"}("{path}")\n'
        f"def {handler}(user = Depends({dependency})):\n"
        f"    ..."
    )
    return (explanation, fix, before, after)


def _sec_003(finding: Finding) -> Rendered:
    metadata = finding.metadata
    with_credentials = bool(metadata.get("allow_credentials"))

    explanation = "CORS is configured with a wildcard origin. " + (
        "Combined with allow_credentials=True this is the most permissive "
        "configuration possible: any website could make authenticated requests "
        "using a logged-in user's cookies. Browsers actually refuse this "
        "combination, so the practical result is a broken app plus a false sense "
        "that cross-origin access works."
        if with_credentials
        else "Any origin can read responses from this API, including ones that "
        "return data specific to the caller."
    )
    fix = (
        f"Replace the wildcard at {_at(finding)} with the exact origins the frontend "
        f"is served from, driven by configuration so staging and production differ."
    )
    before = 'allow_origins=["*"],'
    after = 'allow_origins=settings.cors_origins,  # e.g. ["https://app.example.com"]'
    return (explanation, fix, before, after)


def _sec_004(finding: Finding) -> Rendered:
    metadata = finding.metadata
    path = metadata.get("file", finding.primary_location.file_path)
    keys = metadata.get("credential_keys") or []
    count = metadata.get("variable_count", 0)

    explanation = (
        f"{path} is committed to the repository. A .env file exists specifically to "
        f"stay out of version control, so all {count} values in it are shared with "
        f"everyone who can read the repository — and remain in git history after the "
        f"file is deleted. Credential keys present: {', '.join(keys[:8]) or 'none recognised'}."
    )
    fix = (
        f"Rotate every credential in {path}, then remove the file from tracking and "
        f"ignore it. Commit a .env.example with the keys and no values."
    )
    before = f"# {path} is tracked by git"
    after = (
        f"git rm --cached {path}\n"
        f'echo "{PurePosixPath(path).name}" >> .gitignore\n'
        f"# then rotate every credential the file contained"
    )
    return (explanation, fix, before, after)


def _sec_005(finding: Finding) -> Rendered:
    factory = finding.metadata.get("factory", "the application")

    explanation = (
        f"{factory} is constructed with debug=True. Debug error handlers render stack "
        f"traces, source fragments and local variable values to whoever triggered the "
        f"error, and local variables routinely hold credentials and user data. In "
        f"some frameworks debug mode also exposes an interactive console."
    )
    fix = (
        f"At {_at(finding)}, drive debug from configuration and default it to off so "
        f"production cannot inherit a development setting."
    )
    before = _first_evidence_line(finding)
    after = f'app = {factory}(debug=settings.app_env == "local")'
    return (explanation, fix, before, after)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _dep_001(finding: Finding) -> Rendered:
    metadata = finding.metadata
    package = metadata.get("package", "")
    version = metadata.get("version", "")
    advisories = metadata.get("advisories") or []
    fixes = metadata.get("fixed_versions") or []
    ecosystem = metadata.get("ecosystem", "PyPI")

    explanation = (
        f"{package} is pinned to {version}, which has "
        f"{len(advisories)} published {_plural(len(advisories), 'advisory', 'advisories')} "
        f"({', '.join(advisories[:4])}). The pin means the vulnerable version is what "
        f"gets installed every time, including in production."
    )
    if fixes:
        explanation += f" A patched release exists: {fixes[0]}."
    else:
        explanation += (
            " No patched release is published yet, so a workaround or a replacement is needed."
        )

    target = fixes[0] if fixes else None
    if target is None:
        fix = (
            "No fixed version is available. Check the advisory for a mitigation, or "
            "replace the dependency."
        )
        return (explanation, fix, f"{package}=={version}", "")

    fix = f"Raise the pin at {_at(finding)} to {package} {target} or later, then re-run the tests."
    if ecosystem == "npm":
        before = f'"{package}": "{version}"'
        after = f'"{package}": "{target}"'
    else:
        before = f"{package}=={version}"
        after = f"{package}=={target}"
    return (explanation, fix, before, after)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


def _generic(finding: Finding) -> Rendered:
    """Used only if a rule is registered without a template.

    ``tests/test_explanation_templates.py`` asserts every registered rule has
    one, so reaching this in production means a rule was added without a
    template and the test was skipped.
    """
    definition = finding.definition
    explanation = (
        f"{definition.summary} {definition.rationale} "
        f"Expected {finding.expected or 'the layers to agree'}; found "
        f"{finding.actual or 'a mismatch'}."
    )
    fix = f"Review {_at(finding)} and reconcile the two sides."
    return (explanation, fix, _first_evidence_line(finding), "")


_TEMPLATES: Final[dict[str, Callable[[Finding], Rendered]]] = {
    "MX-API-001": _api_001,
    "MX-API-002": _api_002,
    "MX-API-003": _api_003,
    "MX-API-004": _api_004,
    "MX-API-005": _api_005,
    "MX-DB-001": _db_001,
    "MX-DB-002": _db_002,
    "MX-DB-003": _db_003,
    "MX-DB-004": _db_004,
    "MX-DB-005": _db_005,
    "MX-SEC-001": _sec_001,
    "MX-SEC-002": _sec_002,
    "MX-SEC-003": _sec_003,
    "MX-SEC-004": _sec_004,
    "MX-SEC-005": _sec_005,
    "MX-DEP-001": _dep_001,
}
