import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope


ALLOWED_FUNCTIONS = {
    "AND", "OR", "NOT", "CASE", "IF", "EXISTS",
    "COUNT", "SUM", "AVG", "MIN", "MAX", "COALESCE", "NULLIF",
    "CAST", "EXTRACT", "DATE_PART", "TIMESTAMP_TRUNC", "DATE_TRUNC",
    "TO_CHAR", "LOWER", "UPPER", "LENGTH", "TRIM", "ROUND", "ABS",
    "CEIL", "FLOOR", "CONCAT", "CONCAT_WS", "GREATEST", "LEAST",
    "CURRENT_DATE", "CURRENT_TIMESTAMP", "CURRENT_TIME",
    "ROW_NUMBER", "RANK", "DENSE_RANK",
}
ALLOWED_TYPES = {
    "INT", "BIGINT", "SMALLINT", "DECIMAL", "FLOAT", "DOUBLE", "BOOLEAN",
    "TEXT", "VARCHAR", "CHAR", "DATE", "TIMESTAMP", "TIMESTAMPTZ", "INTERVAL", "UUID",
}


def validate_sql(query: str, database_schema: dict) -> str:
    if not query.strip() or len(query) > 20000:
        raise ValueError("SQL должен быть непустым и не длиннее 20000 символов.")

    try:
        statements = sqlglot.parse(query, read="postgres")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            raise ValueError("Разрешён один SELECT, включая нерекурсивный WITH ... SELECT.")
        tree = statements[0]

        for node in tree.walk():
            if isinstance(node, (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock, exp.Dot)):
                raise ValueError("Запрос содержит неподдерживаемую или изменяющую данные операцию.")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise ValueError("Рекурсивные запросы пока не поддерживаются.")
            if isinstance(node, exp.DataType) and node.this.name not in ALLOWED_TYPES:
                raise ValueError("Запрос использует неподдерживаемый тип данных.")
            if isinstance(node, exp.Func):
                name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
                if name not in ALLOWED_FUNCTIONS:
                    raise ValueError(f"Функция {name} не входит в разрешённый список.")

        for identifier in tree.find_all(exp.Identifier):
            if not identifier.args.get("quoted"):
                identifier.set("this", identifier.this.lower())

        schema_name = database_schema["schema"]
        table_names = {table["name"] for table in database_schema["tables"]}
        for scope in traverse_scope(tree):
            for _, source in scope.selected_sources.values():
                if not isinstance(source, exp.Table):
                    continue
                if not isinstance(source.this, exp.Identifier):
                    raise ValueError("Функции вместо таблиц пока не поддерживаются.")
                if source.catalog or (source.db and source.db != schema_name):
                    raise ValueError("Запрос обращается за пределы выбранной схемы.")
                if source.name not in table_names:
                    raise ValueError(f"Таблица {source.name!r} отсутствует в доступном контексте.")
                source.set("db", exp.Identifier(this=schema_name, quoted=True))

        return tree.sql(dialect="postgres")
    except SqlglotError as error:
        raise ValueError(f"Не удалось разобрать SQL: {error}") from None
