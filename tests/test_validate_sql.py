import unittest

from validate_sql import validate_sql


SCHEMA = {
    "schema": "public",
    "tables": [{"name": name} for name in ("clients", "subscriptions", "payments")],
}


class ValidateSQLTests(unittest.TestCase):
    def test_supported_queries(self):
        queries = [
            "SELECT COUNT(*) FROM clients",
            "SELECT id FROM clients WHERE id > 1 AND id < 3",
            "SELECT 'DELETE FROM clients' AS example FROM clients",
            "WITH c AS (SELECT id FROM clients) SELECT id FROM c",
            "SELECT id FROM clients WHERE EXISTS (SELECT 1 FROM subscriptions WHERE client_id = clients.id)",
            "SELECT CASE WHEN id = 1 THEN 10 ELSE 0 END FROM clients",
            "SELECT p.amount FROM payments p JOIN subscriptions s ON p.subscription_id = s.id",
        ]
        for query in queries:
            with self.subTest(query=query):
                checked = validate_sql(query, SCHEMA)
                self.assertIn('"public".', checked)

    def test_rejects_queries_outside_supported_reading(self):
        queries = [
            "",
            "SELECT 1; DELETE FROM clients",
            "DELETE FROM clients",
            "WITH changed AS (DELETE FROM clients RETURNING *) SELECT * FROM changed",
            "SELECT * INTO stolen FROM clients",
            "SELECT * FROM clients FOR UPDATE",
            "SELECT * FROM pg_catalog.pg_authid",
            "WITH clients AS (SELECT * FROM pg_catalog.pg_authid) SELECT * FROM clients",
            "SELECT * FROM employees",
            "SELECT set_config('transaction_read_only', 'off', true)",
            "SELECT pg_read_file('/etc/passwd')",
            "SELECT pg_sleep(10)",
            "SELECT public.lower('text')",
            "SELECT 'text'::public.custom_type",
            "SELECT * FROM generate_series(1, 1000000)",
            "WITH RECURSIVE t AS (SELECT 1) SELECT * FROM t",
            "COPY clients TO STDOUT",
        ]
        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query, SCHEMA)


if __name__ == "__main__":
    unittest.main()
