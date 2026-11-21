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


def read_constraints(
    connection: psycopg.Connection,
    table_id: int,
    allowed_table_ids: list[int] | None = None,
) -> list[dict]:
    query = """
        SELECT
            constraint_info.conname AS name,
            pg_catalog.pg_get_constraintdef(constraint_info.oid) AS definition
        FROM pg_catalog.pg_constraint AS constraint_info
        WHERE constraint_info.conrelid = %s
            AND constraint_info.contype IN ('p', 'u', 'f', 'c')
            AND (constraint_info.contype <> 'f' OR %s::oid[] IS NULL OR constraint_info.confrelid = ANY(%s::oid[]))
        ORDER BY constraint_info.conname
    """
    return connection.execute(query, (table_id, allowed_table_ids, allowed_table_ids)).fetchall()


def read_foreign_keys(connection: psycopg.Connection, table_ids: list[int]) -> list[dict]:
    query = """
        SELECT
            source.relname AS source_table,
            target.relname AS target_table,
            array_agg(
                pg_catalog.quote_ident(source.relname) || '.' || pg_catalog.quote_ident(source_column.attname)
                || ' = ' ||
                pg_catalog.quote_ident(target.relname) || '.' || pg_catalog.quote_ident(target_column.attname)
                ORDER BY column_pair.position
            ) AS join_on
        FROM pg_catalog.pg_constraint AS fk
        JOIN pg_catalog.pg_class AS source ON source.oid = fk.conrelid
        JOIN pg_catalog.pg_class AS target ON target.oid = fk.confrelid
        CROSS JOIN LATERAL unnest(fk.conkey, fk.confkey) WITH ORDINALITY
            AS column_pair(source_number, target_number, position)
        JOIN pg_catalog.pg_attribute AS source_column
            ON source_column.attrelid = source.oid AND source_column.attnum = column_pair.source_number
        JOIN pg_catalog.pg_attribute AS target_column
            ON target_column.attrelid = target.oid AND target_column.attnum = column_pair.target_number
        WHERE fk.contype = 'f'
            AND fk.conrelid = ANY(%s::oid[])
            AND fk.confrelid = ANY(%s::oid[])
        GROUP BY fk.oid, fk.conname, source.relname, target.relname
        ORDER BY source.relname, target.relname, fk.conname
    """
    return connection.execute(query, (table_ids, table_ids)).fetchall()


def read_schema(
    connection: psycopg.Connection,
    schema_name: str,
    *,
    table_names: list[str] | None = None,
) -> dict:
    if table_names == []:
        raise ValueError("Выбери хотя бы одну таблицу.")
    query = """
        SELECT
            table_info.oid AS table_id,
            table_info.relname AS name,
            pg_catalog.obj_description(table_info.oid, 'pg_class') AS description
        FROM pg_catalog.pg_class AS table_info
        JOIN pg_catalog.pg_namespace AS namespace_info
            ON namespace_info.oid = table_info.relnamespace
        WHERE namespace_info.nspname = %s
            AND (%s::text[] IS NULL OR table_info.relname = ANY(%s::text[]))
            AND table_info.relkind IN ('r', 'p')
            AND pg_catalog.has_schema_privilege(namespace_info.oid, 'USAGE')
            AND pg_catalog.has_table_privilege(table_info.oid, 'SELECT')
        ORDER BY table_info.relname
    """
    tables = connection.execute(query, (schema_name, table_names, table_names)).fetchall()

    if table_names is not None:
        missing = set(table_names) - {table["name"] for table in tables}
        if missing:
            raise ValueError(f"Таблицы недоступны в выбранной схеме: {', '.join(sorted(missing))}.")

    if not tables:
        raise ValueError(f"В схеме {schema_name!r} нет доступных для чтения таблиц.")

    table_ids = [table["table_id"] for table in tables]
    schema = {
        "schema": schema_name,
        "foreign_keys": read_foreign_keys(connection, table_ids),
        "tables": [],
    }
    for table in tables:
        schema["tables"].append(
            {
                "name": table["name"],
                "description": table["description"],
                "columns": read_columns(connection, table["table_id"]),
                "constraints": read_constraints(connection, table["table_id"], table_ids if table_names is not None else None),
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
