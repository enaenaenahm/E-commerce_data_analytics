-- Q3. Какие клиенты чаще возвращаются?
-- Вьюха: заказы клиента по порядку (n = номер заказа, total_orders = всего заказов в периоде)
CREATE OR REPLACE VIEW v_client_orders AS
WITH ord AS (
    SELECT o.order_id,
           o.customer_unique_id,
           o.order_purchase_timestamp AS ts,
           SUM(i.price)               AS order_value
    FROM orders o
    JOIN order_items i USING (order_id)
    WHERE o.is_delivered AND o.in_analysis_period
    GROUP BY o.order_id, o.customer_unique_id, o.order_purchase_timestamp
)
SELECT *,
       ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY ts, order_id) AS n,
       COUNT(*)     OVER (PARTITION BY customer_unique_id)                       AS total_orders
FROM ord;

-- 5a. Сколько заказов приходится на клиента; Repeat Purchase Rate = доля с 2+ заказами
SELECT CASE WHEN total_orders >= 4 THEN '4+' ELSE total_orders::text END AS orders_per_client,
       COUNT(*)                                                         AS clients,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)               AS clients_pct
FROM v_client_orders
WHERE n = 1
GROUP BY 1
ORDER BY 1;

-- 5b. Repeat rate по категории ПЕРВОГО заказа (категория самой дорогой позиции заказа).
-- Порог 1000 клиентов: на малых базах доля повторных шумит (~30 повторных клиентов на 1000).
WITH first_cat AS (
    SELECT DISTINCT ON (r.customer_unique_id)
           r.customer_unique_id, r.total_orders, i.category_en
    FROM v_client_orders r
    JOIN order_items i ON i.order_id = r.order_id
    WHERE r.n = 1
    ORDER BY r.customer_unique_id, i.price DESC, i.order_item_id
)
SELECT category_en,
       COUNT(*)                                        AS clients,
       COUNT(*) FILTER (WHERE total_orders >= 2)       AS repeat_clients,
       ROUND(100.0 * COUNT(*) FILTER (WHERE total_orders >= 2) / COUNT(*), 2) AS repeat_rate_pct
FROM first_cat
GROUP BY category_en
HAVING COUNT(*) >= 1000
ORDER BY repeat_rate_pct DESC;

-- 5c. Через сколько дней приходит второй заказ (и не «разбитая» ли это корзина)
WITH gaps AS (
    SELECT customer_unique_id, n,
           EXTRACT(EPOCH FROM ts - LAG(ts) OVER (PARTITION BY customer_unique_id ORDER BY n)) / 86400
               AS gap_days
    FROM v_client_orders
)
SELECT COUNT(*)                                                         AS clients_with_2nd_order,
       ROUND(100.0 * COUNT(*) FILTER (WHERE gap_days < 1)  / COUNT(*), 1) AS within_1_day_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE gap_days <= 30) / COUNT(*), 1) AS within_30_days_pct,
       ROUND((PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY gap_days))::numeric, 0) AS p25_days,
       ROUND((PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY gap_days))::numeric, 0) AS median_days,
       ROUND((PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY gap_days))::numeric, 0) AS p75_days
FROM gaps
WHERE n = 2;

-- 5d. Возвращаются ли чаще клиенты с дорогим первым заказом (квартили стоимости)
SELECT q                                         AS first_order_value_quartile,
       ROUND(MIN(order_value), 2)                AS min_value,
       ROUND(MAX(order_value), 2)                AS max_value,
       COUNT(*)                                  AS clients,
       ROUND(100.0 * COUNT(*) FILTER (WHERE total_orders >= 2) / COUNT(*), 2) AS repeat_rate_pct
FROM (SELECT *, NTILE(4) OVER (ORDER BY order_value) AS q
      FROM v_client_orders WHERE n = 1) t
GROUP BY q
ORDER BY q;