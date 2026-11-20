BEGIN;

CREATE SCHEMA shop_eval;

CREATE TABLE shop_eval.products (
    id integer PRIMARY KEY,
    name text NOT NULL,
    category text NOT NULL
);

CREATE TABLE shop_eval.orders (
    id integer PRIMARY KEY,
    ordered_on date NOT NULL,
    status text NOT NULL CHECK (status IN ('completed', 'cancelled', 'pending'))
);

CREATE TABLE shop_eval.order_items (
    order_id integer REFERENCES shop_eval.orders(id),
    product_id integer REFERENCES shop_eval.products(id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(10, 2) NOT NULL CHECK (unit_price > 0),
    PRIMARY KEY (order_id, product_id)
);

COMMENT ON TABLE shop_eval.products IS 'Каталог товаров учебного магазина.';
COMMENT ON COLUMN shop_eval.orders.ordered_on IS 'Дата оформления заказа.';
COMMENT ON COLUMN shop_eval.orders.status IS 'completed — завершён, cancelled — отменён, pending — в ожидании. Продажи и выручку считаем только по завершённым заказам.';
COMMENT ON COLUMN shop_eval.order_items.quantity IS 'Количество единиц товара в позиции заказа.';
COMMENT ON COLUMN shop_eval.order_items.unit_price IS 'Цена одной единицы товара в позиции заказа в рублях. Сумма позиции = quantity * unit_price.';

INSERT INTO shop_eval.products VALUES
    (1, 'Кружка', 'посуда'), (2, 'Чайник', 'техника'),
    (3, 'Тарелка', 'посуда'), (4, 'Термос', 'аксессуары');

INSERT INTO shop_eval.orders VALUES
    (1, '2026-09-30', 'completed'), (2, '2026-10-01', 'completed'),
    (3, '2026-10-15', 'completed'), (4, '2026-10-20', 'cancelled'),
    (5, '2026-11-01', 'completed'), (6, '2026-10-31', 'pending');

INSERT INTO shop_eval.order_items VALUES
    (1, 1, 2, 350), (1, 4, 1, 800), (2, 1, 3, 400), (2, 2, 1, 1800),
    (3, 1, 1, 450), (3, 3, 2, 250), (4, 3, 10, 250), (4, 4, 3, 800),
    (5, 2, 2, 1900), (6, 2, 4, 1750);

GRANT USAGE ON SCHEMA shop_eval TO sql_assistant_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA shop_eval TO sql_assistant_reader;

COMMIT;
