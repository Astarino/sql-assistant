import json
import re
import sys
from dataclasses import asdict

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from access_control import grant_options, grant_read, read_roles
from build_context import build_context
from decision import DECISION_SCHEMA, Decision, parse_decision
from execute_sql import execute_sql, reader_connection_url
from ollama_client import request_model


CLARIFICATION_FIELDS = "clarification_fields"
REPAIRABLE_ERRORS = (psycopg.errors.GroupingError, psycopg.errors.UndefinedColumn)
RELATIONSHIP_QUESTIONS = {
    "какие связи есть между таблицами",
    "какие связи между таблицами",
    "как связаны таблицы",
    "покажи связи между таблицами",
    "покажи внешние ключи",
}
COUNT_WITH_DETAILS = re.compile(
    r"\b(?:сколько|общее (?:число|количество))\b.*\b(?:перечисли|и\s+(?:какие|кто|покажи|назови|дай))\b",
    re.IGNORECASE | re.DOTALL,
)
GROUPED_TOTAL = re.compile(
    r"\b(?:по|в разрезе|(?:для|в|у) кажд\w*|сгруппируй|разбей|разных|различных|уникальных)\b",
    re.IGNORECASE,
)
COUNT_QUESTION = re.compile(r"\b(?:сколько|посчитай|подсчитай|количество|число)\b", re.IGNORECASE)
TEXT_FILTER = re.compile(
    r"(?:\b(?P<column>\w+)\s+)?"
    r"\b(?P<condition>(?:(?P<suffix>(?:оканчива|заканчива)\w*)\s+на|начина\w*\s+с)\s+"
    r'(?P<value>«[^»]+»|"[^"]+"|[-@.\w]+?))(?=\s*(?:[),?!]|\.?$))',
    re.IGNORECASE,
)
COMPOUND_FILTER = re.compile(r"\b(?:и|или|либо|кроме|также|но)\b", re.IGNORECASE)
COUNT_INSTRUCTIONS = """
Если нужны общее количество и список тех же записей, используй COUNT(*) OVER () вместе с нужными столбцами.
Например, SELECT COUNT(*) OVER () AS total, name FROM items возвращает список и общее число. Используй реальные имена из схемы.
«Какое общее число записей и перечисли их?» Сохрани отдельную строку для каждой записи.
Контрольный пример: если есть 3 строки, в каждой итог должен быть 3. GROUP BY даёт количество внутри каждой группы.
"""
TEXT_FILTER_INSTRUCTIONS = """
Пользователь дал явный текстовый критерий. Считай совпадения по нему. Для окончания текста используй LIKE '%значение', для начала LIKE 'значение%'.
Применяй условие только к указанному текстовому столбцу. Если он не указан, выбери подходящее поле по схеме.
Применяй заданные пользователем условия и сохрани исходный смысл подсчёта. Дополнительные признаки пола или категории не нужны.
В message опиши критерий. Значение счётчика будет известно после выполнения SQL.
"""
RELATIONSHIP_INSTRUCTIONS = """
Для вопросов о структуре связей, внешних ключах и столбцах для JOIN выбирай action = relationships и sql = null.
Приложение покажет объявленные внешние ключи из database_schema.foreign_keys для выбранных таблиц.
database_schema и join_on содержат метаданные для составления запроса. Для запросов по данным, в которых нужно соединить строки, используй action = sql.
"""
RESPONSE_SCHEMA = {
    **DECISION_SCHEMA,
    "properties": {
        **DECISION_SCHEMA["properties"],
        "action": {
            **DECISION_SCHEMA["properties"]["action"],
            "enum": [*DECISION_SCHEMA["properties"]["action"]["enum"], "relationships"],
        },
        CLARIFICATION_FIELDS: {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
            "maxItems": 3,
        },
    },
    "required": [*DECISION_SCHEMA["required"], CLARIFICATION_FIELDS],
}


def read_catalog(connection: psycopg.Connection) -> dict:
    schemas = connection.execute(
        """
        SELECT namespace.nspname AS name, array_agg(relation.relname ORDER BY relation.relname) AS tables
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_class AS relation ON relation.relnamespace = namespace.oid
        WHERE relation.relkind IN ('r', 'p')
            AND left(namespace.nspname, 3) <> 'pg_'
            AND namespace.nspname <> 'information_schema'
            AND pg_catalog.has_schema_privilege(namespace.oid, 'USAGE')
            AND pg_catalog.has_table_privilege(relation.oid, 'SELECT')
        GROUP BY namespace.nspname
        ORDER BY name
        """
    ).fetchall()
    databases = connection.execute(
        """
        SELECT datname AS name
        FROM pg_catalog.pg_database
        WHERE datallowconn AND NOT datistemplate AND pg_catalog.has_database_privilege(oid, 'CONNECT')
        ORDER BY datname
        """
    )
    return {"database": connection.info.dbname, "databases": [row["name"] for row in databases], "schemas": schemas}


def relationships_response(context: dict) -> dict:
    relationships = context["database_schema"]["foreign_keys"]
    message = (
        "Внешние ключи между выбранными таблицами."
        if relationships else "Между выбранными таблицами нет объявленных внешних ключей."
    )
    return {"action": "relationships", "sql": None, "message": message, "relationships": relationships}


def model_response(question: str, context: dict, *, sql_feedback: dict | None = None) -> dict:
    raw = json.loads(request_model(question, context, "qwen3.5:4b", sql_feedback=sql_feedback))
    if not isinstance(raw, dict):
        raise ValueError("Ответ помощника должен быть JSON-объектом.")
    if raw.get("action") == "relationships":
        return relationships_response(context)
    fields = raw.pop(CLARIFICATION_FIELDS, [])
    decision: Decision = parse_decision(json.dumps(raw, ensure_ascii=False))
    output = asdict(decision)
    if decision.action == "clarify":
        if isinstance(fields, list):
            labels = (field.strip() for field in fields if isinstance(field, str))
            fields = list(dict.fromkeys(label for label in labels if 0 < len(label) <= 80))[:3]
        else:
            fields = []
        output[CLARIFICATION_FIELDS] = fields or ["Твой ответ"]
    return output


def ask(question: str, answers: list[dict], context: dict, connection_url: str) -> dict:
    normalized_question = " ".join(question.casefold().split()).rstrip("?.!").rstrip()
    if normalized_question in RELATIONSHIP_QUESTIONS:
        return relationships_response(context)

    instructions = context["instructions"].replace(
        "Верни только JSON по response_schema с полями action, sql и message.",
        "Если одна разумная трактовка вопроса применима к схеме, а другая требует отсутствующих данных, "
        "уточни смысл. Например, глагол «получает» без объекта может означать доход, выплату или другую метрику. "
        "Выбери unsupported, когда смысл уже понятен и нужных данных в схеме нет.\n"
        "Верни только JSON по response_schema. Для clarify верни в clarification_fields от 1 до 3 "
        "кратких названий полей, например «Год» или «Какие платежи учитывать». "
        "Указывай названия параметров, а не варианты ответов. "
        "Для вопроса «Считать число покупок или сумму продаж? За какой период?» верни [\"Показатель\", \"Период\"]. "
        "Названия должны соответствовать вопросу из message. Для остальных действий верни пустой список.",
    )
    instructions += RELATIONSHIP_INSTRUCTIONS
    if answers:
        details = "\n".join(f'{answer["label"]}: {answer["value"]}' for answer in answers)
        question = f"{question}\n\nУточнения пользователя:\n{details}"
        instructions += (
            "\nЕсли пользователь дал уточнения, следуй последним уточнениям. "
            "При расхождении с исходным вопросом используй формулировку из уточнений."
        )
    total_with_details = bool(COUNT_WITH_DETAILS.search(question) and not GROUPED_TOTAL.search(question))
    if total_with_details:
        instructions += COUNT_INSTRUCTIONS
    text_filter = TEXT_FILTER.search(question) if COUNT_QUESTION.search(question) else None
    requested_filter = None
    if text_filter:
        instructions += TEXT_FILTER_INSTRUCTIONS
        condition = text_filter["condition"]
        column = text_filter["column"]
        if column and any(
            item["name"] == column for table in context["database_schema"]["tables"] for item in table["columns"]
        ):
            condition = f"{column} {condition}"
        else:
            column = None
        if not COMPOUND_FILTER.search(question) and len(list(TEXT_FILTER.finditer(question))) == 1:
            value = text_filter["value"].strip('«»"')
            pattern = f"%{value}" if text_filter["suffix"] else f"{value}%"
            requested_filter = (pattern, column)
        question += (
            f"\nПосчитай число совпадений по буквальному текстовому условию «{condition}». "
            "Назови столбец результата matching_rows."
        )

    context = {**context, "instructions": instructions, "response_schema": RESPONSE_SCHEMA}
    output = model_response(question, context)
    if output["action"] != "sql":
        return output

    for attempt in range(2):
        try:
            result = execute_sql(
                output["sql"], context, reader_url=connection_url,
                total_with_details=total_with_details, text_filter=requested_filter,
            )
        except (psycopg.Error, ValueError) as error:
            output["execution_error"] = str(error)
            if attempt > 0 or not isinstance(error, REPAIRABLE_ERRORS):
                break

            repair_context = {
                **context,
                "instructions": instructions + (
                    "\nPostgreSQL отклонил SQL из sql_feedback. Исправь причину ошибки в рамках исходного вопроса. "
                    "Сохрани нужные столбцы, фильтры и смысл подсчёта. "
                    "Для ошибки группировки проверь, требуется ли общий итог рядом со списком. "
                    "Для неизвестного столбца сверь имена и связи по схеме каждого псевдонима."
                ),
            }
            feedback = {"query": output["sql"], "error": error.diag.message_primary or str(error)}
            if error.diag.message_hint:
                feedback["hint"] = error.diag.message_hint
            try:
                corrected = model_response(question, repair_context, sql_feedback=feedback)
            except (ValueError, KeyError, TypeError, RuntimeError):
                break
            if corrected["action"] != "sql" or corrected["sql"] == output["sql"]:
                break
            output = corrected
        else:
            result["rows"] = [[None if value is None else str(value) for value in row] for row in result["rows"]]
            output["execution"] = result
            if text_filter:
                output["message"] = f"Подсчёт по текстовому условию «{condition}»."
            break
    return output


def handle(request: dict) -> dict:
    action = request["action"]
    settings = request.get("connection")
    if action in {"access_options", "grant_read"} and not settings:
        raise ValueError("Выбери роль, от имени которой выдаётся доступ.")
    if settings:
        connection_url = make_conninfo(
            host=settings["host"] or None,
            port=settings["port"] or None,
            dbname=settings["database"],
            user=settings["user"],
            password=settings["password"] or None,
        )
    else:
        connection_url = reader_connection_url()
    if database := request.get("database"):
        connection_url = make_conninfo(connection_url, dbname=database)
    transaction_mode = "off" if action == "grant_read" else "on"
    with psycopg.connect(
        connection_url,
        row_factory=dict_row,
        connect_timeout=5,
        options=f"-c default_transaction_read_only={transaction_mode} -c statement_timeout=5000 -c search_path=pg_catalog",
    ) as connection:
        if action == "catalog":
            return {"catalog": read_catalog(connection)}
        if action == "roles":
            return {"role_catalog": read_roles(connection)}
        if action == "access_options":
            return {"access_schemas": grant_options(connection, request["role"])}
        if action == "grant_read":
            return {"granted_count": grant_read(connection, request["role"], request["schema"], request["tables"])}
        if action == "schemas":
            catalog = read_catalog(connection)
            return {"database": catalog["database"], "schemas": [schema["name"] for schema in catalog["schemas"]]}
        if action != "ask":
            raise ValueError("Неизвестное действие приложения.")
        context = build_context(connection, request["schema"], table_names=request.get("tables"))

    return ask(request["question"], request.get("answers", []), context, connection_url)


def main() -> None:
    try:
        result = handle(json.load(sys.stdin))
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        result = {"error": str(error)}
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
