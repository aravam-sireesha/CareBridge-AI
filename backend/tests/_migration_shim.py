"""A tiny stand-in for `sqlalchemy` and `alembic.op`, used ONLY when the real libraries are not installed (for example in a
sandbox without network). It translates the handful of operations our additive migrations use into SQLite DDL and runs them
on a real SQLite connection, so the migration files themselves are executed, not just read."""
from __future__ import annotations

import sqlite3
import sys
import types


class _Type:
    def __init__(self, sql): self.sql = sql
    def __call__(self, *a, **k): return self


Integer, Float, DateTime, Text = _Type("INTEGER"), _Type("REAL"), _Type("TIMESTAMP"), _Type("TEXT")
Boolean = _Type("BOOLEAN")


def String(length=None): return _Type("VARCHAR" + (f"({length})" if length else ""))


class ForeignKey:
    def __init__(self, target): self.table, self.column = target.split(".")


class CheckConstraint:
    def __init__(self, text, name=None): self.text, self.name = text, name


class UniqueConstraint:
    def __init__(self, *cols, name=None): self.cols, self.name = cols, name


class _Func:
    @staticmethod
    def now(): return "CURRENT_TIMESTAMP"


func = _Func()


class Column:
    def __init__(self, name, type_, *rest, nullable=True, server_default=None, primary_key=False):
        self.name, self.type, self.nullable, self.default, self.primary_key = name, type_, nullable, server_default, primary_key
        self.fk = next((r for r in rest if isinstance(r, ForeignKey)), None)

    def ddl(self):
        parts = [f'"{self.name}"', self.type.sql]
        if self.primary_key: parts.append("PRIMARY KEY")
        if not self.nullable and not self.primary_key: parts.append("NOT NULL")
        if self.default is not None: parts.append("DEFAULT " + (self.default if self.default == "CURRENT_TIMESTAMP" else f"'{self.default}'"))
        return " ".join(parts)


class _Inspector:
    def __init__(self, conn): self.conn = conn
    def get_table_names(self): return [r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    def get_columns(self, table): return [{"name": r[1], "nullable": not r[3]} for r in self.conn.execute(f'PRAGMA table_info("{table}")')]


def inspect(bind): return _Inspector(bind)


class _Op:
    conn: sqlite3.Connection = None
    def get_bind(self): return self.conn
    def create_table(self, name, *items):
        cols = [i for i in items if isinstance(i, Column)]
        lines = [c.ddl() for c in cols]
        lines += [f'FOREIGN KEY("{c.name}") REFERENCES "{c.fk.table}"("{c.fk.column}")' for c in cols if c.fk]
        lines += [(f'CONSTRAINT "{i.name}" ' if i.name else "") + f"CHECK ({i.text})" for i in items if isinstance(i, CheckConstraint)]
        lines += [(f'CONSTRAINT "{i.name}" ' if i.name else "") + "UNIQUE (" + ", ".join(f'"{c}"' for c in i.cols) + ")" for i in items if isinstance(i, UniqueConstraint)]
        self.conn.execute(f'CREATE TABLE "{name}" ({", ".join(lines)})')
    def add_column(self, table, column):
        if column.fk or (not column.nullable and column.default is None):
            raise AssertionError("an additive migration must not add a NOT NULL column without a default")
        self.conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column.ddl()}')
    def drop_column(self, table, name): self.conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{name}"')
    def create_index(self, name, table, cols, unique=False): self.conn.execute(f'CREATE {"UNIQUE " if unique else ""}INDEX "{name}" ON "{table}" ({", ".join(chr(34)+c+chr(34) for c in cols)})')
    def drop_index(self, name, table_name=None): self.conn.execute(f'DROP INDEX "{name}"')
    def drop_table(self, name): self.conn.execute(f'DROP TABLE "{name}"')


op = _Op()


def install() -> None:
    """Make `import sqlalchemy as sa` and `from alembic import op` resolve to this shim."""
    sa = types.ModuleType("sqlalchemy")
    for n in ("Integer", "Float", "DateTime", "Boolean", "String", "ForeignKey", "CheckConstraint", "UniqueConstraint", "Text", "Column", "func", "inspect"):
        setattr(sa, n, globals()[n])
    alembic = types.ModuleType("alembic"); alembic.op = op
    sys.modules["sqlalchemy"], sys.modules["alembic"] = sa, alembic
