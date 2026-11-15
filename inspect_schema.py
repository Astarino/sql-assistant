import argparse
import json
import os

import psycopg
from psycopg.rows import dict_row


def read_columns(connection: psycopg.Connection, table_id: int) -> list[dict]:
    query = """
        SELECT
            attribute.attname AS name,
            pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) AS data_type,
            NOT attribute.attnotnull AS nullable,
            pg_catalog.col_description(attribute.attrelid, attribute.attnum) AS description
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = %s
            AND attribute.attnum > 0
            AND NOT attribute.attisdropped
        ORDER BY attribute.attnum
    """
    return connection.execute(query, (table_id,)).fetchall()


def read_constraints(connection: psycopg.Connection, table_id: int) -> list[dict]:
    query = """
        SELECT
            constraint_info.conname AS name,
            pg_catalog.pg_get_constraintdef(constraint_info.oid) AS definition
        FROM pg_catalog.pg_constraint AS constraint_info
        WHERE constraint_info.conrelid = %s
            AND constraint_info.contype IN ('p', 'u', 'f', 'c')
        ORDER BY constraint_info.conname
    """
    return connection.execute(query, (table_id,)).fetchall()


def read_schema(connection: psycopg.Connection, schema_name: str) -> dict:
    query = """
        SELECT
            table_info.oid AS table_id,
            table_info.relname AS name,
            pg_catalog.obj_description(table_info.oid, 'pg_class') AS description
        FROM pg_catalog.pg_class AS table_info
        JOIN pg_catalog.pg_namespace AS namespace_info
            ON namespace_info.oid = table_info.relnamespace
        WHERE namespace_info.nspname = %s
            AND table_info.relkind IN ('r', 'p')
            AND pg_catalog.has_schema_privilege(namespace_info.oid, 'USAGE')
            AND pg_catalog.has_table_privilege(table_info.oid, 'SELECT')
        ORDER BY table_info.relname
    """
    tables = connection.execute(query, (schema_name,)).fetchall()

    if not tables:
        raise ValueError(f"В схеме {schema_name!r} нет доступных для чтения таблиц.")

    schema = {"schema": schema_name, "tables": []}
    for table in tables:
        schema["tables"].append(
            {
                "name": table["name"],
                "description": table["description"],
                "columns": read_columns(connection, table["table_id"]),
                "constraints": read_constraints(connection, table["table_id"]),
            }
        )

    return schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Показать структуру базы PostgreSQL в JSON.")
    parser.add_argument("--schema", default="public", help="Схема PostgreSQL (по умолчанию public).")
    arguments = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL", "dbname=sql_assistant_demo")

    try:
        with psycopg.connect(
            database_url,
            row_factory=dict_row,
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        ) as connection:
            schema = read_schema(connection, arguments.schema)
    except (psycopg.Error, ValueError) as error:
        raise SystemExit(f"Не удалось прочитать структуру базы: {error}") from None

    print(json.dumps(schema, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
