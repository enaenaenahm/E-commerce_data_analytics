-- Q6. RFM-сегментация и перспективные сегменты.
-- Снимок на 2018-09-01 (день после конца периода). Клиент = customer_unique_id.
--
-- Важно: 97% клиентов купили один раз, поэтому F нельзя делить на квинтили.
-- F = 1 / 2 / 3+ (три уровня). R и M скорим через CUME_DIST, а не NTILE:
-- NTILE разносит одинаковые значения по разным корзинам произвольно, CUME_DIST даёт одинаковый балл равным значениям.
CREATE OR REPLACE VIEW v_rfm AS
WITH cust AS (
    SELECT o.customer_unique_id,
           DATE '2018-09-01' - MAX(o.order_purchase_timestamp)::date AS recency_days,
           COUNT(DISTINCT o.order_id)                                AS frequency,
           SUM(i.price)                                              AS monetary
    FROM orders o
    JOIN order_items i USING (order_id)
    WHERE o.is_delivered AND o.in_analysis_period
    GROUP BY o.customer_unique_id
), scored AS (
    SELECT *,
           CEIL(5 * CUME_DIST() OVER (ORDER BY recency_days DESC))::int AS r_score, -- 5 = купил недавно
           CASE WHEN frequency >= 3 THEN 3 WHEN frequency = 2 THEN 2 ELSE 1 END AS f_score,
           CEIL(5 * CUME_DIST() OVER (ORDER BY monetary))::int          AS m_score  -- 5 = тратит много
    FROM cust
)
SELECT *,
       CASE
           WHEN f_score >= 2                  THEN '1. Repeat buyers'
           WHEN r_score >= 4 AND m_score >= 4 THEN '2. New high-value'
           WHEN r_score >= 4                  THEN '3. New low-value'
           WHEN r_score = 3                   THEN '4. Cooling (1 order)'
           WHEN m_score >= 4                  THEN '5. At-risk high-value'
           ELSE                                    '6. Lost low-value'
       END AS segment
FROM scored;

-- Сводка по сегментам: размер, доля выручки, средний чек клиента
SELECT segment,
       COUNT(*)                                                    AS clients,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)          AS clients_pct,
       ROUND(SUM(monetary), 2)                                     AS revenue,
       ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 2) AS revenue_pct,
       ROUND(AVG(monetary), 2)                                     AS avg_monetary,
       ROUND(AVG(recency_days), 0)                                 AS avg_recency_days,
       ROUND(AVG(frequency), 2)                                    AS avg_frequency
FROM v_rfm
GROUP BY segment
ORDER BY segment;