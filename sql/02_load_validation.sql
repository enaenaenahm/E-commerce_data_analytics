-- 1. Row counts
SELECT 'products' AS tbl, COUNT(*) FROM products
UNION ALL SELECT 'orders',      COUNT(*) FROM orders
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'payments',    COUNT(*) FROM payments;

-- 2. Выручка delivered (ожидается 13221498.11) и price+freight (15419773.75)
SELECT ROUND(SUM(price), 2)                 AS revenue_price,
       ROUND(SUM(price + freight_value), 2) AS gmv_with_freight
FROM order_items
WHERE order_status = 'delivered';

-- 3. Выручка в периоде анализа (2017-01 .. 2018-08)
SELECT ROUND(SUM(price), 2)         AS revenue_period,
       COUNT(DISTINCT order_id)     AS orders_period
FROM order_items
WHERE order_status = 'delivered' AND in_analysis_period;
-- ожидается orders_period = 96211

-- 4. Целостность: у позиций нет «осиротевших» заказов и статусы согласованы с orders
SELECT COUNT(*) AS status_mismatch
FROM order_items i JOIN orders o USING (order_id)
WHERE i.order_status <> o.order_status;           -- ожидается 0

-- 5. Доля успешных и отменённых заказов (замена конверсии)
SELECT COUNT(*)                                          AS orders_total,
       ROUND(100.0 * AVG(is_delivered::int), 2)          AS delivered_pct,
       ROUND(100.0 * AVG(is_canceled::int), 2)           AS canceled_unavailable_pct
FROM orders;                                      -- ожидается 99441 / 97.02 / 1.24

-- 6. Закрываем недостающий пункт аудита: клиенты и повторные покупки (delivered)
WITH per_client AS (
    SELECT customer_unique_id, COUNT(*) AS n_orders
    FROM orders WHERE is_delivered
    GROUP BY 1
)
SELECT COUNT(*)                                          AS unique_clients,
       COUNT(*) FILTER (WHERE n_orders >= 2)             AS repeat_clients,
       ROUND(100.0 * COUNT(*) FILTER (WHERE n_orders >= 2) / COUNT(*), 2) AS repeat_rate_pct
FROM per_client;

-- 7. Заказы без позиций не должны быть delivered (ожидаются единицы или 0)
SELECT order_status, COUNT(*)
FROM orders o
WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)
GROUP BY 1 ORDER BY 2 DESC;