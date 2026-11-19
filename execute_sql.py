import os

import psycopg
from psycopg import sql

from validate_sql import validate_sql


def check_reader(connection: psycopg.Connection, context: dict) -> None:
    database_name, role_name, privileged = connection.execute(
        """
        SELECT current_database(), current_user,
            rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls
        FROM pg_catalog.pg_roles
        WHERE rolname = current_user
        """
    ).fetchone()
    if database_name != context["database"]:
        raise ValueError("Подключение для выполнения относится к другой базе.")
    if privileged:
        raise ValueError("Для выполнения нужна отдельная роль без административных прав.")

    schema_name = context["database_schema"]["schema"]
    can_create = connection.execute(
        "SELECT pg_catalog.has_schema_privilege(%s, 'CREATE')", (schema_name,)
    ).fetchone()[0]
    if can_create:
        raise ValueError(f"У роли {role_name} есть право создавать объекты в выбранной схеме.")

    for table in context["database_schema"]["tables"]:
        table_name = sql.Identifier(schema_name, table["name"]).as_string(connection)
        can_write = connection.execute(
            "SELECT pg_catalog.has_table_privilege(%s, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
            (table_name,),
        ).fetchone()[0]
        if can_write:
            raise ValueError(f"У роли {role_name} есть права изменения таблицы {table_name}.")


def execute_sql(query: str, context: dict, max_rows: int = 100) -> dict:
    if not 1 <= max_rows <= 100:
        raise ValueError("Лимит результата должен быть от 1 до 100 строк.")
    checked_query = validate_sql(query, context["database_schema"])
    database_url = os.environ.get(
        "SQL_READER_URL", "dbname=sql_assistant_demo user=sql_assistant_reader"
    )

    with psycopg.connect(
        database_url,
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000 -c search_path=pg_catalog",
    ) as connection:
        try:
            check_reader(connection, context)
            connection.execute(sql.SQL("EXPLAIN (FORMAT JSON) {}").format(sql.SQL(checked_query)))
            with connection.cursor(name="assistant_result") as cursor:
                cursor.execute(checked_query)
                rows = cursor.fetchmany(max_rows + 1)
                columns = [column.name for column in cursor.description]
            return {
                "query": checked_query,
                "columns": columns,
                "rows": rows[:max_rows],
                "truncated": len(rows) > max_rows,
            }
        finally:
            connection.rollback()
