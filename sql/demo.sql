BEGIN;

CREATE TABLE public.clients (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name text NOT NULL,
    email text NOT NULL UNIQUE
);

CREATE TABLE public.subscriptions (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id integer NOT NULL REFERENCES public.clients(id),
    plan_name text NOT NULL,
    monthly_price numeric(10, 2) NOT NULL CHECK (monthly_price >= 0),
    started_on date NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'cancelled'))
);

CREATE TABLE public.payments (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subscription_id integer NOT NULL REFERENCES public.subscriptions(id),
    amount numeric(10, 2) NOT NULL CHECK (amount > 0),
    paid_at timestamp with time zone NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'pending', 'failed', 'refunded'))
);

COMMENT ON TABLE public.clients IS 'Клиенты, покупающие подписки. Учебные вымышленные данные.';
COMMENT ON TABLE public.subscriptions IS 'Подписки клиентов на сервис.';
COMMENT ON TABLE public.payments IS 'Платежи клиентов компании за подписки. Одна строка — один платёж.';
COMMENT ON COLUMN public.clients.full_name IS 'Имя клиента, не сотрудника компании.';
COMMENT ON COLUMN public.subscriptions.monthly_price IS 'Стоимость месяца подписки в рублях, не сумма фактических оплат.';
COMMENT ON COLUMN public.subscriptions.status IS 'active — действующая подписка; cancelled — отменённая.';
COMMENT ON COLUMN public.payments.amount IS 'Сумма платежа клиента компании в рублях.';
COMMENT ON COLUMN public.payments.paid_at IS 'Время операции; для неоплаченного платежа — время попытки оплаты.';
COMMENT ON COLUMN public.payments.status IS 'completed — оплачен; pending — ожидает оплаты; failed — не оплачен; refunded — полностью возвращён клиенту. Возврат меняет статус исходной строки.';

INSERT INTO public.clients (full_name, email) VALUES
    ('Алина Смирнова', 'alina@example.com'),
    ('Борис Волков', 'boris@example.com'),
    ('Вера Орлова', 'vera@example.com');

INSERT INTO public.subscriptions (client_id, plan_name, monthly_price, started_on, status) VALUES
    (1, 'Basic', 990, '2026-09-01', 'active'),
    (2, 'Pro', 1990, '2026-10-01', 'active'),
    (3, 'Basic', 990, '2026-09-10', 'cancelled'),
    (1, 'Pro', 1990, '2026-11-01', 'active');

INSERT INTO public.payments (subscription_id, amount, paid_at, status) VALUES
    (1, 990, '2026-09-01 10:00:00+03', 'completed'),
    (1, 990, '2026-10-01 10:00:00+03', 'completed'),
    (2, 1990, '2026-10-02 12:00:00+03', 'completed'),
    (3, 990, '2026-10-10 14:00:00+03', 'refunded'),
    (2, 1990, '2026-11-02 12:00:00+03', 'failed'),
    (4, 1990, '2026-11-03 09:00:00+03', 'pending');

COMMIT;
