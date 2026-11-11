-- Q2a. AOV по месяцам
WITH m AS (
    SELECT purchase_month,
           SUM(price)                 AS revenue,
           SUM(price + freight_value) AS gmv_with_freight,
           COUNT(DISTINCT order_id)   AS orders,
           COUNT(*)                   AS items
    FROM order_items
    WHERE order_status = 'delivered' AND in_analysis_period
    GROUP BY purchase_month
), a AS (
    SELECT *, revenue / orders AS aov FROM m
)
SELECT purchase_month,
       ROUND(revenue, 2)                          AS revenue,
       orders,
       ROUND(aov, 2)                              AS aov,
       ROUND(gmv_with_freight / orders, 2)        AS aov_with_freight,
       ROUND(items::numeric / orders, 3)          AS items_per_order,
       ROUND(100 * (aov / NULLIF(LAG(aov) OVER (ORDER BY purchase_month), 0) - 1), 2)
                                                  AS aov_mom_pct,
       ROUND(AVG(aov) OVER (ORDER BY purchase_month
             ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS aov_ma3  -- скользящее среднее 3 мес.
FROM a
ORDER BY purchase_month;

-- Q2b. Среднее vs медиана: AOV чувствителен к дорогим заказам
WITH o AS (
    SELECT order_id, SUM(price) AS order_value
    FROM order_items
    WHERE order_status = 'delivered' AND in_analysis_period
    GROUP BY order_id
)
SELECT COUNT(*)                                                           AS orders,
       ROUND(AVG(order_value), 2)                                         AS aov_mean,
       ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY order_value))::numeric, 2) AS median_order,
       ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY order_value))::numeric, 2) AS p90_order
FROM o;