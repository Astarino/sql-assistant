import unittest

from validate_sql import validate_sql


SCHEMA = {
    "schema": "public",
    "tables": [{"name": name} for name in ("clients", "subscriptions", "payments")],
}


class ValidateSQLTests(unittest.TestCase):
    def test_total_with_details_counts_all_rows(self):
        for group in ("", " GROUP BY full_name, email"):
            query = "SELECT COUNT(*) AS total, full_name, email FROM clients" + group
            with self.subTest(query=query):
                self.assertEqual(
                    validate_sql(query, SCHEMA, total_with_details=True),
                    'SELECT COUNT(*) OVER () AS total, full_name, email FROM "public".clients',
                )

    def test_grouped_query_preserves_counts_by_default(self):
        query = "SELECT COUNT(*) AS total, status FROM payments GROUP BY status"
        self.assertEqual(
            validate_sql(query, SCHEMA),
            'SELECT COUNT(*) AS total, status FROM "public".payments GROUP BY status',
        )

    def test_single_text_filter_keeps_the_requested_pattern_and_column(self):
        cases = (
            ("full_name LIKE '%ов' AND LOWER(full_name) LIKE '%м%'", ("%ов", None), "full_name LIKE '%ов'"),
            ("full_name LIKE '%@example.com' OR email LIKE '%@example.com'", ("%@example.com", "email"), "email LIKE '%@example.com'"),
            ("full_name LIKE '%ов' AND id > 1", ("%ов", None), "full_name LIKE '%ов' AND id > 1"),
        )
        for predicates, text_filter, expected in cases:
            with self.subTest(predicates=predicates):
                query = f"SELECT COUNT(*) FROM clients WHERE {predicates}"
                self.assertEqual(
                    validate_sql(query, SCHEMA, text_filter=text_filter),
                    f'SELECT COUNT(*) FROM "public".clients WHERE {expected}',
                )

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
