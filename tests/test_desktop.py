import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from access_control import grant_options, grant_read, read_roles
from desktop import ask, handle
from instructions import ASSISTANT_INSTRUCTIONS


QUESTION = "Покажи общее число клиентов, их имена и почту."
INVALID_SQL = "SELECT COUNT(*), full_name, email FROM clients"
CORRECTED_SQL = "SELECT COUNT(*) OVER (), full_name, email FROM clients"


def sql_response(query: str) -> str:
    return json.dumps({"action": "sql", "sql": query, "message": "Данные клиентов."})


class DesktopTests(unittest.TestCase):
    def test_grant_requires_explicit_connection(self):
        with patch("desktop.psycopg.connect") as connect:
            for action in ("access_options", "grant_read"):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    handle({"action": action})
            connect.assert_not_called()

    def test_relationships_from_model_action_only_use_schema_metadata(self):
        relationship = {
            "source_table": "payments",
            "target_table": "subscriptions",
            "join_on": ["payments.subscription_id = subscriptions.id"],
        }
        context = {"instructions": ASSISTANT_INSTRUCTIONS, "database_schema": {"foreign_keys": [relationship]}}
        response = json.dumps({"action": "relationships", "sql": "SELECT 1", "relationships": []})
        with patch("desktop.request_model", return_value=response), patch("desktop.execute_sql") as execute:
            result = ask("Как платежи связаны с подписками?", [], context, "reader")

        self.assertEqual(result["relationships"], [relationship])
        self.assertIsNone(result["sql"])
        execute.assert_not_called()

    def test_repairs_grouping_error_with_original_question_and_sql(self):
        database_result = {"query": CORRECTED_SQL, "rows": [(3, "Клиент", "client@example.com")]}
        with (
            patch("desktop.request_model", side_effect=[sql_response(INVALID_SQL), sql_response(CORRECTED_SQL)]) as model,
            patch("desktop.execute_sql", side_effect=[psycopg.errors.GroupingError("grouping error"), database_result]) as execute,
        ):
            result = ask(QUESTION, [], {"instructions": ASSISTANT_INSTRUCTIONS}, "reader")

        self.assertEqual(result["sql"], CORRECTED_SQL)
        self.assertEqual(result["execution"]["rows"], [["3", "Клиент", "client@example.com"]])
        self.assertNotIn("execution_error", result)
        self.assertEqual(model.call_args.args[0], QUESTION)
        self.assertEqual(model.call_args.kwargs["sql_feedback"], {"query": INVALID_SQL, "error": "grouping error"})
        self.assertEqual([call.args[0] for call in execute.call_args_list], [INVALID_SQL, CORRECTED_SQL])

    def test_stops_after_one_failed_repair(self):
        with (
            patch("desktop.request_model", side_effect=[sql_response(INVALID_SQL), sql_response(CORRECTED_SQL)]) as model,
            patch("desktop.execute_sql", side_effect=psycopg.errors.UndefinedColumn("unknown column")) as execute,
        ):
            result = ask(QUESTION, [], {"instructions": ASSISTANT_INSTRUCTIONS}, "reader")

        self.assertEqual(result["execution_error"], "unknown column")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(execute.call_count, 2)

    def test_permission_error_is_not_sent_back_for_repair(self):
        with (
            patch("desktop.request_model", return_value=sql_response(CORRECTED_SQL)) as model,
            patch("desktop.execute_sql", side_effect=psycopg.errors.InsufficientPrivilege("permission denied")),
        ):
            result = ask(QUESTION, [], {"instructions": ASSISTANT_INSTRUCTIONS}, "reader")

        self.assertEqual(result["execution_error"], "permission denied")
        model.assert_called_once()


@unittest.skipUnless(os.environ.get("RUN_DB_TESTS") == "1", "Нужны учебная база и роль из sql/reader.sql")
class SourceSelectionTests(unittest.TestCase):
    def test_grants_only_selected_tables_to_a_reader(self):
        suffix = uuid4().hex
        reader = f"sql_assistant_test_reader_{suffix}"
        schema = f"Access Test {suffix}"
        selected, unselected = "Selected.Table", "Unselected"
        with psycopg.connect(dbname="sql_assistant_demo", row_factory=dict_row) as connection:
            try:
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(reader)))
                connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                for table in (selected, unselected):
                    connection.execute(sql.SQL("CREATE TABLE {} (id int)").format(sql.Identifier(schema, table)))

                catalog = read_roles(connection)
                self.assertEqual(catalog["database"], "sql_assistant_demo")
                self.assertIn(reader, [role["name"] for role in catalog["roles"]])
                options = grant_options(connection, reader)
                self.assertIn({"name": schema, "tables": [selected, unselected]}, options)
                with self.assertRaises(ValueError):
                    grant_read(connection, catalog["current_role"], schema, [selected])
                with self.assertRaises(ValueError):
                    grant_read(connection, reader, schema, [selected, "Missing"])

                status = connection.execute(
                    "SELECT pg_catalog.has_schema_privilege(%s, %s, 'USAGE') AS allowed", (reader, schema)
                ).fetchone()
                self.assertFalse(status["allowed"])
                self.assertEqual(grant_read(connection, reader, schema, [selected, selected]), 1)
                connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(reader)))
                tables = connection.execute(
                    """
                    SELECT has_table_privilege(%s, 'SELECT') AS readable,
                        has_table_privilege(%s, 'INSERT') AS writable,
                        has_table_privilege(%s, 'SELECT') AS other_readable
                    """,
                    (
                        sql.Identifier(schema, selected).as_string(connection),
                        sql.Identifier(schema, selected).as_string(connection),
                        sql.Identifier(schema, unselected).as_string(connection),
                    ),
                ).fetchone()
                self.assertEqual(tables, {"readable": True, "writable": False, "other_readable": False})
            finally:
                connection.rollback()

    def test_relationship_question_respects_selected_tables_without_model(self):
        request = {
            "action": "ask", "database": "sql_assistant_demo", "schema": "public",
            "question": "Какие связи есть между таблицами?",
        }
        with patch("desktop.request_model") as model, patch("desktop.execute_sql") as execute:
            result = handle({**request, "tables": ["payments", "subscriptions"]})
            self.assertEqual(result["action"], "relationships")
            self.assertEqual(len(result["relationships"]), 1)
            self.assertEqual(result["relationships"][0]["join_on"], ["payments.subscription_id = subscriptions.id"])
            self.assertEqual(handle({**request, "tables": ["payments"]})["relationships"], [])
            model.assert_not_called()
            execute.assert_not_called()

    def test_selected_table_limits_context_and_execution(self):
        request = {
            "action": "ask", "database": "sql_assistant_demo", "schema": "public",
            "tables": ["subscriptions"], "question": "Сколько записей?",
        }
        with patch("desktop.request_model", side_effect=[
            sql_response("SELECT COUNT(*) FROM subscriptions"),
            sql_response("SELECT COUNT(*) FROM clients"),
        ]) as model:
            self.assertTrue(handle(request)["execution"]["rows"])
            self.assertIn("отсутствует в доступном контексте", handle(request)["execution_error"])

        schema = model.call_args.args[1]["database_schema"]
        self.assertEqual([table["name"] for table in schema["tables"]], ["subscriptions"])
        self.assertFalse(schema["foreign_keys"])
        self.assertFalse(any("FOREIGN KEY" in item["definition"] for item in schema["tables"][0]["constraints"]))

    def test_invalid_table_selection_stops_before_model(self):
        for tables in ([], ["missing_table"]):
            with self.subTest(tables=tables), patch("desktop.request_model") as model:
                with self.assertRaises(ValueError):
                    handle({
                        "action": "ask", "database": "sql_assistant_demo", "schema": "public",
                        "tables": tables, "question": "Сколько записей?",
                    })
                model.assert_not_called()
