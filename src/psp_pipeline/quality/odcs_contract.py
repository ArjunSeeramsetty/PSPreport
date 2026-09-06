"""Evaluate Open Data Contract Standard (ODCS) YAML specs against SQLite.

The evaluator implements the subset required by this pipeline: required
fields, primary-key uniqueness, and numeric quality bounds. Empty tables are
skipped so coverage fixtures without regional facts do not fail closed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

import yaml


@dataclass(frozen=True)
class OdcsContractResult:
    """Outcome of one ODCS YAML contract against a SQLite database."""

    contract_id: str
    table_name: str
    passed: bool
    skipped: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready evaluation payload."""

        payload = asdict(self)
        payload["failures"] = list(self.failures)
        return payload


@dataclass(frozen=True)
class OdcsDirectoryResult:
    """Aggregate of every contract file in a directory."""

    passed: bool
    skipped: bool
    failures: tuple[str, ...]
    contracts: tuple[OdcsContractResult, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready directory evaluation payload."""

        return {
            "passed": self.passed,
            "skipped": self.skipped,
            "failures": list(self.failures),
            "contracts": [result.as_dict() for result in self.contracts],
        }


def default_odcs_directory() -> Path:
    """Return the committed ODCS contract directory."""

    return Path(__file__).resolve().parents[3] / "config" / "contracts"


def load_odcs_contract(path: Path | str) -> dict[str, Any]:
    """Load one ODCS YAML document.

    Raises:
        ValueError: If the file is not a mapping with an id and schema.
    """

    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ValueError(f"ODCS contract {path} must declare id")
    if not payload.get("schema"):
        raise ValueError(f"ODCS contract {path} must declare schema")
    return payload


def evaluate_odcs_contract(
    db_path: Path | str,
    contract: Mapping[str, Any] | Path | str,
) -> OdcsContractResult:
    """Evaluate one contract against landed SQLite tables."""

    spec = (
        load_odcs_contract(contract)
        if isinstance(contract, (Path, str))
        else dict(contract)
    )
    schema = _first_schema(spec)
    table_name = str(schema.get("physicalName") or schema.get("name") or "")
    contract_id = str(spec.get("id") or table_name)
    properties = list(schema.get("properties") or [])
    if not table_name:
        return OdcsContractResult(
            contract_id=contract_id,
            table_name="",
            passed=False,
            skipped=False,
            failures=("missing_physical_name",),
        )
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, table_name):
            return OdcsContractResult(
                contract_id=contract_id,
                table_name=table_name,
                passed=True,
                skipped=True,
                failures=(),
            )
        row_count = int(
            conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        )
        if row_count == 0:
            return OdcsContractResult(
                contract_id=contract_id,
                table_name=table_name,
                passed=True,
                skipped=True,
                failures=(),
            )
        present = {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")
        }
        failures: list[str] = []
        primary_columns: list[str] = []
        for prop in properties:
            name = str(prop.get("name") or "")
            if not name:
                continue
            if prop.get("required") and name not in present:
                failures.append(f"{table_name}.{name}: missing required column")
                continue
            if prop.get("primary"):
                primary_columns.append(name)
            if prop.get("required") and name in present:
                nulls = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {table_name} WHERE {name} IS NULL"
                    ).fetchone()[0]
                )
                if nulls:
                    failures.append(
                        f"{table_name}.{name}: {nulls} null values violate required: true"
                    )
            quality = prop.get("quality") or []
            if isinstance(quality, list):
                failures.extend(
                    _evaluate_quality_rules(conn, table_name, name, quality)
                )
        if primary_columns and all(column in present for column in primary_columns):
            joined = ", ".join(primary_columns)
            duplicates = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM ("
                    f"SELECT {joined}, COUNT(*) AS n FROM {table_name} "
                    f"GROUP BY {joined} HAVING n > 1)"
                ).fetchone()[0]
            )
            if duplicates:
                failures.append(
                    f"{table_name}: {duplicates} duplicate grain(s) on {joined}"
                )
    finally:
        conn.close()
    return OdcsContractResult(
        contract_id=contract_id,
        table_name=table_name,
        passed=not failures,
        skipped=False,
        failures=tuple(failures),
    )


def evaluate_odcs_directory(
    db_path: Path | str,
    directory: Path | str | None = None,
) -> OdcsDirectoryResult:
    """Evaluate every ``*.yaml`` contract in the committed contracts directory."""

    root = Path(directory) if directory is not None else default_odcs_directory()
    paths = sorted(root.glob("*.yaml")) if root.is_dir() else []
    results = tuple(evaluate_odcs_contract(db_path, path) for path in paths)
    failures = tuple(
        failure
        for result in results
        for failure in result.failures
    )
    skipped = bool(results) and all(result.skipped for result in results)
    if not results:
        skipped = True
    passed = not failures
    return OdcsDirectoryResult(
        passed=passed,
        skipped=skipped,
        failures=failures,
        contracts=results,
    )


def _first_schema(spec: Mapping[str, Any]) -> dict[str, Any]:
    schema = spec.get("schema")
    if isinstance(schema, list) and schema:
        first = schema[0]
        return dict(first) if isinstance(first, dict) else {}
    if isinstance(schema, dict):
        return dict(schema)
    return {}


def _evaluate_quality_rules(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    rules: Iterable[Mapping[str, Any]],
) -> list[str]:
    failures: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        minimum = rule.get("mustBeGreaterThan")
        maximum = rule.get("mustBeLessThan")
        if minimum is None and maximum is None:
            continue
        if column_name not in {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")
        }:
            continue
        clauses: list[str] = [f"{column_name} IS NOT NULL"]
        params: list[object] = []
        if minimum is not None:
            clauses.append(f"{column_name} <= ?")
            params.append(minimum)
        if maximum is not None:
            clauses.append(f"{column_name} >= ?")
            params.append(maximum)
        count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0]
        )
        if count:
            failures.append(
                f"{table_name}.{column_name}: {count} value(s) outside "
                f"({minimum}, {maximum})"
            )
    return failures


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None
