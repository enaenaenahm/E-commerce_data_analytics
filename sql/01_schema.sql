-- Схема очищенных данных Olist. Скрипт идемпотентный: можно запускать повторно.
DROP TABLE IF EXISTS order_items, payments, orders, products CASCADE;

CREATE TABLE products (
    product_id   TEXT PRIMARY KEY,
    category_pt  TEXT NOT NULL,
    category_en  TEXT NOT NULL            -- 'unknown' для товаров без категории
);

CREATE TABLE orders (
    order_id                       TEXT PRIMARY KEY,
    customer_id                    TEXT NOT NULL,   -- уникален на заказ, для анализа клиентов НЕ использовать
    order_status                   TEXT NOT NULL,
    order_purchase_timestamp       TIMESTAMP NOT NULL,
    order_approved_at              TIMESTAMP,
    order_delivered_carrier_date   TIMESTAMP,
    order_delivered_customer_date  TIMESTAMP,
    order_estimated_delivery_date  TIMESTAMP,
    customer_unique_id             TEXT NOT NULL,   -- настоящий идентификатор клиента
    is_delivered                   BOOLEAN NOT NULL,
    is_canceled                    BOOLEAN NOT NULL,
    purchase_month                 DATE NOT NULL,
    in_analysis_period             BOOLEAN NOT NULL,
    delivery_date_missing          BOOLEAN NOT NULL
);

CREATE TABLE order_items (
    order_id                  TEXT NOT NULL REFERENCES orders(order_id),
    order_item_id             INT  NOT NULL,
    product_id                TEXT NOT NULL,
    seller_id                 TEXT,
    shipping_limit_date       TIMESTAMP,
    price                     NUMERIC(12,2) NOT NULL CHECK (price > 0),
    freight_value             NUMERIC(12,2) NOT NULL CHECK (freight_value >= 0),
    customer_unique_id        TEXT NOT NULL,
    order_status              TEXT NOT NULL,
    order_purchase_timestamp  TIMESTAMP NOT NULL,
    purchase_month            DATE NOT NULL,
    in_analysis_period        BOOLEAN NOT NULL,
    category_en               TEXT NOT NULL,
    line_revenue              NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE payments (
    order_id              TEXT NOT NULL,
    payment_sequential    INT  NOT NULL,
    payment_type          TEXT,
    payment_installments  INT,
    payment_value         NUMERIC(12,2) NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE INDEX ix_orders_unique_cust ON orders (customer_unique_id);
CREATE INDEX ix_orders_month       ON orders (purchase_month);
CREATE INDEX ix_items_cust         ON order_items (customer_unique_id);
CREATE INDEX ix_items_category     ON order_items (category_en);
CREATE INDEX ix_items_month        ON order_items (purchase_month);