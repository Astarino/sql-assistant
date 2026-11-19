BEGIN;

CREATE ROLE sql_assistant_reader
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

GRANT CONNECT ON DATABASE sql_assistant_demo TO sql_assistant_reader;
GRANT USAGE ON SCHEMA public TO sql_assistant_reader;
GRANT SELECT ON public.clients, public.subscriptions, public.payments TO sql_assistant_reader;
ALTER ROLE sql_assistant_reader SET default_transaction_read_only = on;

COMMIT;
