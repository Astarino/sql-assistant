from psycopg import Connection, sql


USER_TABLES = """
    SELECT relation.oid, namespace.oid AS schema_oid, namespace.nspname AS schema, relation.relname AS name
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE relation.relkind IN ('r', 'p')
        AND left(namespace.nspname, 3) <> 'pg_'
        AND namespace.nspname <> 'information_schema'
"""


def read_roles(connection: Connection) -> dict:
    server = connection.execute(
        """
        SELECT current_user AS current_role, pg_catalog.pg_get_userbyid(datdba) AS owner
        FROM pg_catalog.pg_database WHERE datname = current_database()
        """
    ).fetchone()
    roles = connection.execute(
        """
        WITH user_tables AS ({})
        SELECT role.rolname AS name,
            role.rolsuper OR role.rolcreatedb OR role.rolcreaterole
                OR role.rolreplication OR role.rolbypassrls AS administrator,
            pg_catalog.has_database_privilege(role.oid, db.oid, 'CONNECT') AS can_connect,
            pg_catalog.has_database_privilege(role.oid, db.oid, 'CREATE') OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace AS namespace
                WHERE left(namespace.nspname, 3) <> 'pg_'
                    AND namespace.nspname <> 'information_schema'
                    AND pg_catalog.has_schema_privilege(role.oid, namespace.oid, 'CREATE')
            ) OR EXISTS (
                SELECT 1 FROM user_tables AS t
                WHERE pg_catalog.has_table_privilege(role.oid, t.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
            ) AS can_write,
            (
                SELECT count(*) FROM user_tables AS t
                WHERE pg_catalog.has_schema_privilege(role.oid, t.schema_oid, 'USAGE')
                    AND pg_catalog.has_table_privilege(role.oid, t.oid, 'SELECT')
            ) AS readable_tables
        FROM pg_catalog.pg_roles AS role
        JOIN pg_catalog.pg_database AS db ON db.datname = current_database()
        WHERE role.rolcanlogin AND left(role.rolname, 3) <> 'pg_'
        ORDER BY role.rolname
        """.format(USER_TABLES)
    ).fetchall()
    return {
        **server, "database": connection.info.dbname, "host": connection.info.host,
        "port": str(connection.info.port), "roles": roles,
    }


def require_reader(connection: Connection, role: str) -> None:
    reader = next((candidate for candidate in read_roles(connection)["roles"] if candidate["name"] == role), None)
    if reader is None or reader["administrator"] or reader["can_write"] or not reader["can_connect"]:
        raise ValueError("Для помощника выбери роль с входом в эту базу и без прав записи или администрирования.")


def grant_options(connection: Connection, role: str) -> list[dict]:
    require_reader(connection, role)
    return connection.execute(
        """
        WITH user_tables AS ({})
        SELECT t.schema AS name, array_agg(t.name ORDER BY t.name) AS tables
        FROM user_tables AS t
        WHERE pg_catalog.has_table_privilege(t.oid, 'SELECT WITH GRANT OPTION')
            AND (pg_catalog.has_schema_privilege(t.schema_oid, 'USAGE WITH GRANT OPTION')
                OR pg_catalog.has_schema_privilege(%s, t.schema_oid, 'USAGE'))
        GROUP BY t.schema
        ORDER BY t.schema
        """.format(USER_TABLES),
        (role,),
    ).fetchall()


def grant_read(connection: Connection, role: str, schema: str, tables: list[str]) -> int:
    if not isinstance(tables, list) or not tables or not all(isinstance(table, str) for table in tables):
        raise ValueError("Отметь таблицы, к которым нужно выдать чтение.")
    selected = list(dict.fromkeys(tables))
    options = grant_options(connection, role)
    available = next((item["tables"] for item in options if item["name"] == schema), [])
    if not set(selected).issubset(available):
        raise ValueError("У этой роли выдачи нет прав на одну или несколько выбранных таблиц.")

    recipient = sql.Identifier(role)
    schema_name = sql.Identifier(schema)
    if not connection.execute(
        "SELECT pg_catalog.has_schema_privilege(%s, %s, 'USAGE') AS allowed", (role, schema)
    ).fetchone()["allowed"]:
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema_name, recipient))

    qualified_tables = [sql.Identifier(schema, table) for table in selected]
    connection.execute(
        sql.SQL("GRANT SELECT ON TABLE {} TO {}").format(sql.SQL(", ").join(qualified_tables), recipient)
    )
    permissions = connection.execute(
        """
        SELECT pg_catalog.has_schema_privilege(%s, %s, 'USAGE') AND bool_and(
            pg_catalog.has_table_privilege(%s, table_name, 'SELECT')
        ) AS allowed
        FROM unnest(%s::text[]) AS table_name
        """,
        (role, schema, role, [name.as_string(connection) for name in qualified_tables]),
    ).fetchone()
    if not permissions["allowed"]:
        raise ValueError("PostgreSQL не выдал чтение на все выбранные таблицы. Изменения отменены.")
    return len(selected)
