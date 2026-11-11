-- Q4. Какие категории снижают продажи?
-- Сравниваем последние 3 полных месяца (июнь–авг 2018) с предыдущими 3 (март–май 2018).
-- Окно выбрано так, чтобы не попасть на пик ноября–декабря 2017 (иначе «падение» будет сезонным).
CREATE OR REPLACE VIEW v_category_3m AS
SELECT category_en,
       SUM(price) FILTER (WHERE purchase_month BETWEEN DATE '2018-03-01' AND DATE '2018-05-01') AS prev3m,
       SUM(price) FILTER (WHERE purchase_month BETWEEN DATE '2018-06-01' AND DATE '2018-08-01') AS last3m
FROM order_items
WHERE order_status = 'delivered' AND in_analysis_period
GROUP BY category_en;

-- 7a. Рост/падение категории и отставание от рынка. Порог базы 20 000 R$ в prev3m, чтобы не ловить шум.
WITH t AS (SELECT SUM(prev3m) AS p, SUM(last3m) AS l FROM v_category_3m)
SELECT c.category_en,
       ROUND(c.prev3m, 2)                                     AS prev3m,
       ROUND(c.last3m, 2)                                     AS last3m,
       ROUND(100 * (c.last3m / c.prev3m - 1), 2)              AS growth_pct,
       ROUND(100 * (t.l / t.p - 1), 2)                        AS market_growth_pct,
       ROUND(100 * (c.last3m / c.prev3m - 1) - 100 * (t.l / t.p - 1), 2) AS vs_market_pp
FROM v_category_3m c CROSS JOIN t
WHERE c.prev3m >= 20000
ORDER BY growth_pct;

-- 7b. Помесячная динамика и MoM для 10 худших категорий (источник для графика в Tableau).
-- Календарь месяцев строим явно, иначе LAG сравнит с «предыдущей существующей» строкой, а не с прошлым месяцем.
WITH decliners AS (
    SELECT category_en FROM v_category_3m
    WHERE prev3m >= 20000 AND last3m < prev3m
    ORDER BY last3m / prev3m
    LIMIT 10
), months AS (
    SELECT generate_series(DATE '2017-01-01', DATE '2018-08-01', INTERVAL '1 month')::date AS purchase_month
), monthly AS (
    SELECT category_en, purchase_month, SUM(price) AS revenue
    FROM order_items
    WHERE order_status = 'delivered' AND in_analysis_period
    GROUP BY category_en, purchase_month
), grid AS (
    SELECT d.category_en, m.purchase_month, COALESCE(mo.revenue, 0) AS revenue
    FROM decliners d CROSS JOIN months m
    LEFT JOIN monthly mo ON mo.category_en = d.category_en AND mo.purchase_month = m.purchase_month
)
SELECT category_en, purchase_month,
       ROUND(revenue, 2) AS revenue,
       ROUND(100 * (revenue / NULLIF(LAG(revenue) OVER w, 0) - 1), 1) AS mom_pct,
       ROUND(AVG(revenue) OVER (w ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS ma3
FROM grid
WINDOW w AS (PARTITION BY category_en ORDER BY purchase_month)
ORDER BY category_en, purchase_month;