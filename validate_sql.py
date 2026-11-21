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


def add_total_to_rows(tree: exp.Select) -> None:
    source = tree.args.get("from_")
    if source is None or not isinstance(source.this, exp.Table):
        return
    if any(tree.args.get(clause) for clause in ("joins", "with_", "distinct", "having", "qualify")):
        return

    fields = [item.unalias() for item in tree.expressions]
    columns = [item for item in fields if isinstance(item, exp.Column)]
    counts = [item for item in fields if isinstance(item, exp.Count) and isinstance(item.this, exp.Star)]
    if not columns or len(counts) != 1 or len(fields) != len(columns) + 1:
        return
    if len(list(tree.find_all(exp.AggFunc))) != 1:
        return

    group = tree.args.get("group")
    if group is not None and (group.args.keys() != {"expressions"} or set(group.expressions) != set(columns)):
        return

    count = counts[0]
    count.replace(exp.Window(this=count.copy()))
    tree.set("group", None)


def keep_requested_text_filter(tree: exp.Select, pattern: str, column: str | None) -> None:
    if len(tree.expressions) != 1 or not isinstance(tree.expressions[0].unalias(), exp.Count) or tree.args.get("joins"):
        return
    where = tree.args.get("where")
    if where is None or not isinstance(where.this, (exp.And, exp.Or)):
        return
    predicates = list(where.this.flatten())
    if not all(isinstance(item, (exp.Like, exp.ILike)) and isinstance(item.expression, exp.Literal) for item in predicates):
        return

    columns = [item.this.find(exp.Column) for item in predicates]
    if any(field is None for field in columns):
        return
    matches = [
        (item, field) for item, field in zip(predicates, columns)
        if item.expression.this == pattern and (column is None or field.name == column)
    ]
    if len(matches) != 1:
        return
    match, selected_column = matches[0]
    if all(field == selected_column or (column and item.expression.this == pattern) for item, field in zip(predicates, columns)):
        where.set("this", match.copy())


def validate_sql(
    query: str,
    database_schema: dict,
    *,
    total_with_details: bool = False,
    text_filter: tuple[str, str | None] | None = None,
) -> str:
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

        if total_with_details:
            add_total_to_rows(tree)
        if text_filter is not None:
            keep_requested_text_filter(tree, *text_filter)
        return tree.sql(dialect="postgres")
    except SqlglotError as error:
        raise ValueError(f"Не удалось разобрать SQL: {error}") from None
