import os
import unittest
from decimal import Decimal
from unittest.mock import patch

import psycopg

from build_context import load_context
from execute_sql import execute_sql


@unittest.skipUnless(os.environ.get("RUN_DB_TESTS") == "1", "Нужны учебная база и роль из sql/reader.sql")
class ExecuteSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = load_context("public")
        if cls.context["database"] != "sql_assistant_demo":
            raise ValueError("Интеграционные тесты рассчитаны только на учебную базу.")

    def test_count_clients(self):
        result = execute_sql("SELECT COUNT(*) AS total_clients FROM clients", self.context)
        self.assertEqual(result["columns"], ["total_clients"])
        self.assertEqual(result["rows"], [(3,)])
        self.assertFalse(result["truncated"])

    def test_cte(self):
        result = execute_sql("WITH c AS (SELECT id FROM clients) SELECT id FROM c ORDER BY id", self.context)
        self.assertEqual(result["rows"], [(1,), (2,), (3,)])

    def test_correct_join_and_paid_amounts(self):
        query = """
            SELECT c.id, COALESCE(SUM(p.amount), 0) AS paid
            FROM clients c
            LEFT JOIN subscriptions s ON s.client_id = c.id
            LEFT JOIN payments p ON p.subscription_id = s.id
                AND p.status = 'completed'
                AND p.paid_at >= '2026-10-01 00:00:00+03'::timestamptz
                AND p.paid_at < '2026-11-01 00:00:00+03'::timestamptz
            GROUP BY c.id ORDER BY c.id
        """
        result = execute_sql(query, self.context)
        self.assertEqual(result["rows"], [(1, Decimal("990")), (2, Decimal("1990")), (3, Decimal("0"))])

    def test_missing_column_is_rejected(self):
        query = "SELECT c.id FROM clients c JOIN payments p ON p.client_id = c.id"
        with self.assertRaises(psycopg.errors.UndefinedColumn):
            execute_sql(query, self.context)

    def test_row_limit(self):
        query = "SELECT a.id, b.id, c.id FROM clients a CROSS JOIN clients b CROSS JOIN clients c"
        result = execute_sql(query, self.context, max_rows=5)
        self.assertEqual(len(result["rows"]), 5)
        self.assertTrue(result["truncated"])

    def test_administrative_connection_is_rejected(self):
        with patch.dict(os.environ, {"SQL_READER_URL": "dbname=sql_assistant_demo"}):
            with self.assertRaises(ValueError):
                execute_sql("SELECT COUNT(*) FROM clients", self.context)

    def test_reader_cannot_update_even_in_read_write_transaction(self):
        with psycopg.connect("dbname=sql_assistant_demo user=sql_assistant_reader") as connection:
            connection.read_only = False
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute("UPDATE public.clients SET full_name = full_name WHERE false")


if __name__ == "__main__":
    unittest.main()
