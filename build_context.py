import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from decision import DECISION_SCHEMA
from inspect_schema import read_schema
from instructions import ASSISTANT_INSTRUCTIONS


def load_glossary(path: Path, database_name: str, database_schema: dict) -> dict:
    glossary = json.loads(path.read_text(encoding="utf-8"))

    if glossary["database"] != database_name or glossary["schema"] != database_schema["schema"]:
        raise ValueError("Словарь относится к другой базе или схеме. Выбери подходящий файл или запусти без --glossary.")

    table_names = {table["name"] for table in database_schema["tables"]}
    missing_tables = set(glossary["tables"]) - table_names
    if missing_tables:
        raise ValueError(f"В базе нет таблиц из словаря: {', '.join(sorted(missing_tables))}.")

    return glossary


def build_context(
    connection: psycopg.Connection,
    schema_name: str,
    glossary_path: Path | None = None,
) -> dict:
    database_name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
    database_schema = read_schema(connection, schema_name)
    glossary = None
    if glossary_path is not None:
        glossary = load_glossary(glossary_path, database_name, database_schema)

    return {
        "database": database_name,
        "instructions": ASSISTANT_INSTRUCTIONS,
        "database_schema": database_schema,
        "domain_glossary": glossary,
        "response_schema": DECISION_SCHEMA,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Собрать контекст базы для SQL-помощника.")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--glossary", type=Path, help="Необязательный словарь выбранной базы.")
    arguments = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "dbname=sql_assistant_demo")

    try:
        with psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            context = build_context(connection, arguments.schema, arguments.glossary)
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Не удалось собрать контекст: {error}") from None

    print(json.dumps(context, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
