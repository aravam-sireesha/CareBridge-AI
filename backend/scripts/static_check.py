"""Static consistency check. Needs only the Python standard library: no database, no FastAPI, no SQLAlchemy.

    python scripts/static_check.py

It cannot replace running the test-suite, but it catches the mistakes that most often break a first run:
  1. code or tests that use a model class or column that does not exist (typos, renamed columns);
  2. model constructors called with keyword arguments that are not columns;
  3. test requests to URLs that no router serves (wrong path or method);
  4. names that are used but never imported or defined (the 'forgot to import Optional' class of crash);
  5. columns a model defines that no Alembic migration ever creates (the "users.failed_login_count" class of bug).
Exit status is 1 when it finds a problem.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP, TESTS, VERSIONS = ROOT / "app", ROOT / "tests", ROOT / "alembic" / "versions"
problems: list[str] = []
notes: list[str] = []


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --------------------------------------------------------------------------- models
def load_models() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for node in parse(APP / "models.py").body:
        if not isinstance(node, ast.ClassDef):
            continue
        info = {"table": None, "columns": {}, "other": set()}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name, value = stmt.targets[0].id, stmt.value
                if name == "__tablename__" and isinstance(value, ast.Constant):
                    info["table"] = value.value
                elif isinstance(value, ast.Call) and getattr(value.func, "id", getattr(value.func, "attr", "")) == "Column":
                    nullable = True
                    for kw in value.keywords:
                        if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                            nullable = bool(kw.value.value)
                        if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant) and kw.value.value:
                            nullable = False
                    info["columns"][name] = {"nullable": nullable}
                else:
                    info["other"].add(name)          # relationship(), constants, __table_args__ ...
        if info["table"]:
            out[node.name] = info
    return out


MODELS = load_models()


def check_usage() -> None:
    files = [p for p in list(APP.rglob("*.py")) + list(TESTS.rglob("*.py")) if "alembic" not in p.parts]
    for path in files:
        tree = parse(path)
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            # from app.models import A, B   /   from ..models import A, B
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[-1] == "models" and (node.level or node.module.startswith("app")):
                for alias in node.names:
                    if alias.name != "*" and alias.name not in MODELS and alias.name[0].isupper() and alias.name not in ("Base",):
                        problems.append(f"{rel}:{node.lineno} imports model '{alias.name}' which does not exist in app/models.py")
            # models.Class  /  models.Class.column  /  models.Class(kw=...)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "models":
                if node.attr[0].isupper() and node.attr not in MODELS and node.attr != "Base":
                    problems.append(f"{rel}:{node.lineno} uses models.{node.attr}, which does not exist")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id == "models":
                cls, col = node.value.attr, node.attr
                if cls in MODELS and not col.startswith("_") and col not in MODELS[cls]["columns"] and col not in MODELS[cls]["other"] and col not in ("query", "metadata", "registry"):
                    problems.append(f"{rel}:{node.lineno} uses models.{cls}.{col}, but {cls} has no such column")
            if isinstance(node, ast.Call):
                fn = node.func
                cls = None
                if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "models" and fn.attr in MODELS:
                    cls = fn.attr
                elif isinstance(fn, ast.Name) and fn.id in MODELS:
                    cls = fn.id
                if cls:
                    for kw in node.keywords:
                        if kw.arg and kw.arg not in MODELS[cls]["columns"] and kw.arg not in MODELS[cls]["other"]:
                            problems.append(f"{rel}:{node.lineno} {cls}({kw.arg}=...) but {cls} has no column '{kw.arg}'")


# --------------------------------------------------------------------------- routes vs tests
def literal_prefix(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return ""


def load_routes() -> list[tuple[str, re.Pattern]]:
    mounts: dict[str, str] = {}                  # router module -> prefix given in include_router(...)
    for node in ast.walk(parse(APP / "main.py")):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "include_router" and node.args:
            target = node.args[0]
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                mounts[target.value.id] = literal_prefix(node)
    routes = []
    for path in (APP / "routers").glob("*.py"):
        tree = parse(path)
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                prefix = literal_prefix(node)
        extra = mounts.get(path.stem, "")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ("get", "post", "put", "patch", "delete") and dec.args and isinstance(dec.args[0], ast.Constant):
                        full = (extra + prefix + dec.args[0].value) or "/"
                        rx = "^" + re.sub(r"\{[^}]+\}", "[^/]+", re.escape(full).replace(r"\{", "{").replace(r"\}", "}")) + "/?$"
                        rx = re.sub(r"\\\[\^/\]\+", "[^/]+", rx)
                        routes.append((dec.func.attr, re.compile(rx.replace("\\{", "{"))))
    for node in ast.walk(parse(APP / "main.py")):             # routes declared directly in main.py (@app.get(...))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "app" \
                        and dec.func.attr in ("get", "post", "put", "patch", "delete") and dec.args and isinstance(dec.args[0], ast.Constant):
                    routes.append((dec.func.attr, re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(dec.args[0].value)) + "/?$")))
    return routes


def check_tests_against_routes() -> None:
    routes = load_routes()
    notes.append(f"{len(routes)} routes found in app/routers")
    call_rx = re.compile(r"""client\.(get|post|put|patch|delete)\(\s*f?(["'])(/[^"']*)\2""")
    seen = 0
    for path in TESTS.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for m in call_rx.finditer(text):
            method, url = m.group(1), re.sub(r"\{[^}]*\}", "1", m.group(3)).split("?")[0]
            line_text = text.splitlines()[text.count("\n", 0, m.start())]
            if re.search(r"\b(404|405)\b", line_text):        # a deliberate "this must not exist" test
                continue
            seen += 1
            if not any(rm == method and rx.match(url) for rm, rx in routes):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{path.relative_to(ROOT)}:{line} calls {method.upper()} {url}, but no router serves it")
    notes.append(f"{seen} test requests checked against the route table")


# --------------------------------------------------------------------------- models vs migrations
def migrated_columns() -> tuple[dict[str, set[str]], int]:
    """Columns created by the migration chain, read from op.create_table / op.add_column / op.drop_column calls."""
    tables: dict[str, set[str]] = {}
    created: set[str] = set()                    # tables some migration creates (the rest come from the legacy base schema)
    unreadable: set[str] = set()                 # tables built dynamically (loops, helper functions): cannot be judged statically
    unparsed = 0
    ordered = []
    for path in VERSIONS.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision[^=]*=\s*['\"]([^'\"]+)", src, re.M).group(1)
        down = re.search(r"^down_revision[^=]*=\s*(None|['\"]([^'\"]+))", src, re.M)
        ordered.append((rev, down.group(2) if down and down.group(2) else None, path))
    by_rev = {r: (d, p) for r, d, p in ordered}
    chain, cur = [], [r for r in by_rev if r not in {d for d, _ in by_rev.values()}][0]
    while cur:
        chain.append(cur)
        cur = by_rev[cur][0]
    for rev in reversed(chain):
        tree = parse(by_rev[rev][1])
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade"]:
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                name = node.func.attr
                def col_names(args):
                    return [a.args[0].value for a in args if isinstance(a, ast.Call) and getattr(a.func, "attr", "") == "Column" and a.args and isinstance(a.args[0], ast.Constant)]
                if name == "create_table" and node.args and isinstance(node.args[0], ast.Constant):
                    created.add(node.args[0].value)
                    cols = set(col_names(node.args[1:]))
                    if any(isinstance(a, ast.Starred) for a in node.args[1:]):      # columns built elsewhere: *cols
                        unreadable.add(node.args[0].value)
                        unparsed += 1
                    tables.setdefault(node.args[0].value, set()).update(cols)
                elif name == "add_column" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                    added = col_names(node.args[1:2])
                    if not added:                                                    # sa.Column(name, ...) with a variable name
                        unreadable.add(node.args[0].value)
                    tables.setdefault(node.args[0].value, set()).update(added)
                elif name == "add_column" and node.args and not isinstance(node.args[0], ast.Constant):
                    unparsed += 1                                                    # table name is a variable: a loop over tables
                elif name == "drop_column" and len(node.args) >= 2 and all(isinstance(a, ast.Constant) for a in node.args[:2]):
                    tables.get(node.args[0].value, set()).discard(node.args[1].value)
                elif name == "drop_table" and node.args and isinstance(node.args[0], ast.Constant):
                    tables.pop(node.args[0].value, None)
                elif name in ("batch_alter_table", "execute"):
                    unparsed += 1
    return {t: c for t, c in tables.items() if t not in unreadable}, unparsed, unreadable, created


def check_models_vs_migrations() -> None:
    tables, unparsed, unreadable, created = migrated_columns()
    # Migrations here build some tables with loops or helper functions, which a static reader cannot follow. Those tables are
    # skipped (and listed) instead of being reported as missing.
    for cls, info in MODELS.items():
        table = info["table"]
        if table in unreadable:
            notes.append(f"table '{table}' ({cls}) is built dynamically by a migration: covered by tests/test_migrations_sqlite.py, not by this script")
            continue
        if table not in created and table in tables:
            notes.append(f"table '{table}' ({cls}) pre-dates the migrations (legacy base schema); migrations only alter it, so its original columns cannot be checked here")
            continue
        if table not in tables:
            notes.append(f"table '{table}' ({cls}) is not created by a statically readable migration (created by the legacy base schema, or built dynamically)")
            continue
        missing = [c for c in info["columns"] if c not in tables[table]]
        if missing:
            problems.append(f"model {cls} ('{table}') defines columns that no migration adds: {', '.join(missing)}")
    if unparsed:
        notes.append(f"{unparsed} migration operations were too dynamic to read statically")


# --------------------------------------------------------------------------- undefined names (missing imports, typos)
import builtins as _builtins

_BUILTINS = set(dir(_builtins)) | {"__file__", "__name__", "__doc__"}


def check_undefined_names() -> None:
    """A name that is read but never bound anywhere in its file (no import, assignment, def, class, argument or loop variable).
    Scope-insensitive on purpose (cheap, few false alarms): it catches the classic 'used Optional but never imported'."""
    for path in sorted(list(APP.rglob("*.py")) + list(TESTS.rglob("*.py")) + list((ROOT / "scripts").glob("*.py"))):
        try:
            tree = parse(path)
        except SyntaxError as e:
            problems.append(f"{path.relative_to(ROOT)}: syntax error {e}")
            continue
        bound: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    bound.add((a.asname or a.name).split(".")[0])
            if isinstance(node, ast.arg):
                bound.add(node.arg)
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)
            if isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                bound.update(node.names)
            if isinstance(node, ast.MatchAs) if hasattr(ast, "MatchAs") else False:
                if node.name:
                    bound.add(node.name)
        if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree)):
            continue                                                             # star import: cannot know
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound and node.id not in _BUILTINS:
                problems.append(f"{path.relative_to(ROOT)}:{node.lineno} uses '{node.id}', which is never imported or defined in this file")


if __name__ == "__main__":
    check_usage()
    check_tests_against_routes()
    check_models_vs_migrations()
    check_undefined_names()
    print(f"models read: {len(MODELS)}")
    for n in notes:
        print("note:", n)
    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in sorted(set(problems)):
            print(" -", p)
        sys.exit(1)
    print("\nOK: no inconsistencies found")
