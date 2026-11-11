-- Q5. Как меняется покупательская активность?
-- «Новый» клиент = первый delivered-заказ в этом месяце. Первый месяц считаем по ВСЕМ delivered-заказам
-- (включая 2016), иначе клиенты 2016 года ошибочно стали бы «новыми» в 2017.
WITH d AS (
    SELECT customer_unique_id, order_id, purchase_month
    FROM orders
    WHERE is_delivered
), first_m AS (
    SELECT customer_unique_id, MIN(purchase_month) AS first_month
    FROM d GROUP BY customer_unique_id
), m AS (
    SELECT d.purchase_month,
           COUNT(DISTINCT d.customer_unique_id) AS active_clients,
           COUNT(DISTINCT d.order_id)           AS orders,
           COUNT(DISTINCT d.customer_unique_id)
               FILTER (WHERE d.purchase_month = f.first_month) AS new_clients
    FROM d JOIN first_m f USING (customer_unique_id)
    WHERE d.purchase_month BETWEEN DATE '2017-01-01' AND DATE '2018-08-01'
    GROUP BY d.purchase_month
)
SELECT purchase_month,
       active_clients,
       new_clients,
       active_clients - new_clients                                         AS returning_clients,
       ROUND(100.0 * (active_clients - new_clients) / active_clients, 2)    AS returning_share_pct,
       orders,
       ROUND(orders::numeric / active_clients, 3)                           AS orders_per_client,
       ROUND(100 * (active_clients::numeric / NULLIF(LAG(active_clients) OVER (ORDER BY purchase_month), 0) - 1), 2) AS active_mom_pct,
       ROUND(100 * (orders::numeric / NULLIF(LAG(orders) OVER (ORDER BY purchase_month), 0) - 1), 2)                 AS orders_mom_pct
FROM m
ORDER BY purchase_month;