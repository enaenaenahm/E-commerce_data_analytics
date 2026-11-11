-- Q1. Какие категории приносят наибольшую выручку?
WITH cat AS (
    SELECT category_en,
           SUM(price)               AS revenue,
           COUNT(DISTINCT order_id) AS orders,
           COUNT(*)                 AS items,
           AVG(price)               AS avg_item_price
    FROM order_items
    WHERE order_status = 'delivered' AND in_analysis_period
    GROUP BY category_en
)
SELECT RANK() OVER (ORDER BY revenue DESC)                       AS rnk,
       category_en,
       ROUND(revenue, 2)                                         AS revenue,
       ROUND(100 * revenue / SUM(revenue) OVER (), 2)            AS share_pct,
       -- накопленная доля (Парето): сколько категорий дают основную выручку
       ROUND(100 * SUM(revenue) OVER (ORDER BY revenue DESC
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                 / SUM(revenue) OVER (), 2)                      AS cum_share_pct,
       orders,
       items,
       ROUND(avg_item_price, 2)                                  AS avg_item_price
FROM cat
ORDER BY revenue DESC;