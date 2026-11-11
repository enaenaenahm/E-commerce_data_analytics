"""
src/export_to_tableau.py — звёздная схема для Tableau Public (data/tableau/*.csv)
и сверка с pandas-итогами и PostgreSQL.

Запуск:  python src/export_to_tableau.py          # с проверкой в PostgreSQL
         python src/export_to_tableau.py --no-sql # без БД
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

PROC, OUT = Path("data/processed"), Path("data/tableau")
OUT.mkdir(parents=True, exist_ok=True)

P_START, P_END = pd.Timestamp("2017-01-01"), pd.Timestamp("2018-08-31")
PREV3M = pd.date_range("2018-03-01", "2018-05-01", freq="MS")   # как в sql/07
LAST3M = pd.date_range("2018-06-01", "2018-08-01", freq="MS")
DECLINE_MIN_BASE, TOP_DECLINERS = 20_000, 8

DSN = "postgresql+psycopg2://{u}:{p}@{h}:{port}/{db}".format(
    u=os.getenv("PG_USER", "analyst"), p=os.getenv("PG_PASSWORD", "analyst_pwd"),
    h=os.getenv("PG_HOST", "localhost"), port=os.getenv("PG_PORT", "5432"),
    db=os.getenv("PG_DB", "ecommerce"))

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✔' if ok else '✘'} {name} {detail}")
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------- построение таблиц
def build_fact(items: pd.DataFrame) -> pd.DataFrame:
    f = items[(items.order_status == "delivered") & items.in_analysis_period].copy()
    f["purchase_date"] = f.order_purchase_timestamp.dt.normalize()
    cols = ["order_id", "order_item_id", "customer_unique_id", "product_id", "category_en",
            "purchase_date", "purchase_month", "price", "freight_value"]
    return f[cols].sort_values(["purchase_date", "order_id", "order_item_id"]).reset_index(drop=True)


def build_dim_customer(rfm: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    per = orders[orders.is_delivered & orders.in_analysis_period]
    span = (per.groupby("customer_unique_id").order_purchase_timestamp
               .agg(first_ts="min", last_ts="max").reset_index())
    # когорта — по ВСЕМ delivered-заказам (включая 2016), как в sql/08
    cohort = (orders[orders.is_delivered].groupby("customer_unique_id").purchase_month
              .min().rename("cohort_month").reset_index())
    d = (rfm.merge(span, on="customer_unique_id", validate="1:1")
            .merge(cohort, on="customer_unique_id", validate="1:1"))

    d["is_repeat"] = (d.frequency >= 2).astype(int)
    d["is_repeat_after_24h"] = ((d.last_ts - d.first_ts) >= pd.Timedelta(days=1)).astype(int)
    d["first_order_date"] = d.first_ts.dt.normalize()

    short = {1: "Repeat buyers", 2: "New high-value", 3: "New low-value",
             4: "Cooling", 5: "Dormant high-value", 6: "Lost low-value"}
    d["segment_order"] = d.segment.str[0].astype(int)
    d["segment_name"] = d.segment_order.map(short)

    # Описания порогов берём из данных, а не пишем руками
    recent_max = int(d.loc[d.r_score >= 4, "recency_days"].max())
    cool = d.loc[d.r_score == 3, "recency_days"]
    old_min = int(d.loc[d.r_score <= 2, "recency_days"].min())
    hv = d.loc[d.m_score >= 4, "monetary"].min()
    desc = {1: "2+ заказа в периоде",
            2: f"1 заказ, покупка ≤{recent_max} дн. назад, сумма ≥ R$ {hv:.2f}",
            3: f"1 заказ, покупка ≤{recent_max} дн. назад, сумма < R$ {hv:.2f}",
            4: f"1 заказ, покупка {cool.min()}–{cool.max()} дн. назад",
            5: f"1 заказ, покупка ≥{old_min} дн. назад, сумма ≥ R$ {hv:.2f}",
            6: f"1 заказ, покупка ≥{old_min} дн. назад, сумма < R$ {hv:.2f}"}
    d["segment_desc"] = d.segment_order.map(desc)

    cols = ["customer_unique_id", "segment", "segment_name", "segment_order", "segment_desc",
            "r_score", "f_score", "m_score", "recency_days", "frequency", "monetary",
            "is_repeat", "is_repeat_after_24h", "first_order_date", "cohort_month"]
    return d[cols]


def build_dim_category(fact: pd.DataFrame) -> pd.DataFrame:
    m = (fact.groupby(["category_en", "purchase_month"]).price.sum()
             .unstack(fill_value=0))
    prev = m.reindex(columns=PREV3M, fill_value=0).sum(axis=1)
    last = m.reindex(columns=LAST3M, fill_value=0).sum(axis=1)
    market = 100 * (last.sum() / prev.sum() - 1)

    c = pd.DataFrame({"revenue": fact.groupby("category_en").price.sum()})
    c["revenue_share_pct"] = 100 * c.revenue / c.revenue.sum()
    c["revenue_rank"] = c.revenue.rank(ascending=False, method="first").astype(int)
    c["is_top10"] = (c.revenue_rank <= 10).astype(int)
    c["prev3m"], c["last3m"] = prev, last
    c["change_rub"] = c.last3m - c.prev3m
    c["growth_pct"] = np.where(c.prev3m > 0, 100 * (c.last3m / c.prev3m - 1), np.nan)
    c["market_growth_pct"] = market
    c["vs_market_pp"] = c.growth_pct - market
    c["is_decliner"] = ((c.prev3m >= DECLINE_MIN_BASE) & (c.last3m < c.prev3m)).astype(int)
    # ранг падения по абсолютной потере в рублях (1 = самая большая потеря)
    c["decliner_rank"] = c.change_rub.where(c.is_decliner == 1).rank(method="first")
    c["is_top_decliner"] = (c.decliner_rank <= TOP_DECLINERS).astype(int)
    c = c.reset_index()
    c["category_label"] = c.category_en.str.replace("_", " ").str.capitalize()
    return c.round(2)


def build_dim_date() -> pd.DataFrame:
    d = pd.DataFrame({"calendar_date": pd.date_range(P_START, P_END, freq="D")})
    s = d.calendar_date
    d["year"], d["month_num"] = s.dt.year, s.dt.month
    d["quarter"] = "Q" + s.dt.quarter.astype(str)
    d["month_start"] = s.dt.to_period("M").dt.to_timestamp()
    d["year_month"] = s.dt.strftime("%Y-%m")
    d["weekday_num"], d["weekday"] = s.dt.dayofweek + 1, s.dt.day_name()
    return d


def build_cohort(ret: pd.DataFrame) -> pd.DataFrame:
    r = ret.copy()
    r["cohort_label"] = r.cohort_month.dt.strftime("%Y-%m")
    r["k_label"] = "M" + r.k.astype(str)
    return r[["cohort_month", "cohort_label", "k", "k_label",
              "retained_clients", "cohort_size", "retention_pct"]]


# ---------------------------------------------------------------- проверки без БД
def checks_python(fact, dim_c, dim_cat, dim_d, coh) -> None:
    print("\nПроверки (pandas):")
    check("revenue = 13 181 027.13", int((fact.price * 100).round().sum()) == 1_318_102_713)
    check("orders = 96 211", fact.order_id.nunique() == 96_211)
    check("clients = 93 104 и совпадают с dim_customer",
          fact.customer_unique_id.nunique() == len(dim_c) == 93_104
          and fact.customer_unique_id.isin(dim_c.customer_unique_id).all())
    check("revenue по клиентам (dim_customer) = revenue fact",
          abs(dim_c.monetary.sum() - fact.price.sum()) < 0.01)
    check("все категории fact есть в dim_category (74)",
          fact.category_en.isin(dim_cat.category_en).all() and len(dim_cat) == 74)
    check("все даты fact есть в dim_date (608 дней)",
          fact.purchase_date.isin(dim_d.calendar_date).all() and len(dim_d) == 608)
    check("ключи уникальны", dim_c.customer_unique_id.is_unique
          and dim_cat.category_en.is_unique and dim_d.calendar_date.is_unique)

    m = fact.groupby("purchase_month").agg(active=("customer_unique_id", "nunique"),
                                           orders=("order_id", "nunique"))
    check("активные клиенты и заказы совпали с sql/08 (янв-17, ноя-17, авг-18)",
          (m.loc["2017-01-01"].tolist(), m.loc["2017-11-01"].tolist(), m.loc["2018-08-01"].tolist())
          == ([718, 750], [7183, 7289], [6310, 6351]))

    check("падающих категорий 22 из 31 (как в sql/07)",
          (dim_cat.prev3m >= DECLINE_MIN_BASE).sum() == 31 and dim_cat.is_decliner.sum() == 22)
    check("рынок Jun–Aug против Mar–May = -11.77%",
          round(dim_cat.market_growth_pct.iloc[0], 2) == -11.77)
    top = set(dim_cat.loc[dim_cat.is_top_decliner == 1, "category_en"])
    expected = {"computers_accessories", "sports_leisure", "watches_gifts", "baby",
                "cool_stuff", "office_furniture", "garden_tools", "furniture_decor"}
    check("топ-8 падающих по потерям в рублях", top == expected, f"(получено: {sorted(top)})")

    check("когорты: 210 ячеек, k=0 суммарно 93 094", len(coh) == 210
          and coh.loc[coh.k == 0, "retained_clients"].sum() == 93_094)
    print(f"  i  Repeat rate: {100*dim_c.is_repeat.mean():.2f}% | "
          f"после 24 ч: {100*dim_c.is_repeat_after_24h.mean():.2f}%")


# ---------------------------------------------------------------- сверка с PostgreSQL
def checks_sql(fact, dim_c, dim_cat) -> None:
    print("\nПроверки (PostgreSQL):")
    base = "FROM order_items WHERE order_status = 'delivered' AND in_analysis_period"
    eng = create_engine(DSN)
    with eng.connect() as conn:
        q = lambda s: pd.read_sql(text(s), conn)

        t = q(f"SELECT COUNT(*) AS n, ROUND(SUM(price),2) AS rev, "
              f"COUNT(DISTINCT order_id) AS o, COUNT(DISTINCT customer_unique_id) AS c {base}").iloc[0]
        check("итого: строки, выручка, заказы, клиенты",
              (int(t.n), float(t.rev), int(t.o), int(t.c))
              == (len(fact), round(fact.price.sum(), 2), fact.order_id.nunique(),
                  fact.customer_unique_id.nunique()),
              f"(SQL: {int(t.n)} строк, {float(t.rev):,.2f})")

        s = q(f"SELECT category_en, ROUND(SUM(price),2) AS rev {base} GROUP BY 1").set_index("category_en").rev.astype(float)
        p = dim_cat.set_index("category_en").revenue
        check("выручка по 74 категориям", len(s) == len(p) and (s - p.reindex(s.index)).abs().max() < 0.01)

        s = q(f"SELECT purchase_month AS m, ROUND(SUM(price),2) AS revenue, COUNT(DISTINCT order_id) AS orders, "
              f"COUNT(DISTINCT customer_unique_id) AS active {base} GROUP BY 1 ORDER BY 1")
        s["m"] = pd.to_datetime(s.m)
        s = s.set_index("m").astype(float)
        pm = fact.groupby("purchase_month").agg(revenue=("price", "sum"), orders=("order_id", "nunique"),
                                                active=("customer_unique_id", "nunique")).astype(float)
        pm["revenue"] = pm.revenue.round(2)
        check("месяцы: выручка, заказы, активные клиенты (20 мес.)",
              s.index.equals(pm.index) and np.allclose(s.values, pm.values, atol=0.01))

        s = q("SELECT LEFT(segment,1) AS s, COUNT(*) AS clients, ROUND(SUM(monetary),2) AS rev "
              "FROM v_rfm GROUP BY 1 ORDER BY 1").astype({"clients": int, "rev": float})
        p = dim_c.groupby(dim_c.segment_order.astype(str)).agg(
            clients=("customer_unique_id", "size"), rev=("monetary", "sum")).round(2)
        check("RFM-сегменты (клиенты и выручка) vs v_rfm",
              s.clients.tolist() == p.clients.tolist() and np.allclose(s.rev, p.rev, atol=0.01))

        r = q("SELECT COUNT(*) AS c, COUNT(*) FILTER (WHERE total_orders >= 2) AS rep "
              "FROM v_client_orders WHERE n = 1").iloc[0]
        r24 = q("WITH f AS (SELECT customer_unique_id, MIN(ts) a, MAX(ts) b FROM v_client_orders GROUP BY 1) "
                "SELECT COUNT(*) FILTER (WHERE b - a >= INTERVAL '1 day') AS rep24 FROM f").iloc[0]
        check("Repeat rate: классический и после 24 ч (это же запрос 5e)",
              (int(r.rep), int(r24.rep24)) == (int(dim_c.is_repeat.sum()), int(dim_c.is_repeat_after_24h.sum())),
              f"(SQL: {int(r.rep)} и {int(r24.rep24)} клиентов)")


# ---------------------------------------------------------------- main
def main(no_sql: bool) -> None:
    items = pd.read_csv(PROC / "order_items.csv",
                        parse_dates=["order_purchase_timestamp", "purchase_month"])
    orders = pd.read_csv(PROC / "orders.csv",
                         parse_dates=["order_purchase_timestamp", "purchase_month"])
    rfm = pd.read_csv(PROC / "rfm.csv")
    ret = pd.read_csv(PROC / "cohort_retention.csv", parse_dates=["cohort_month"])

    fact = build_fact(items)
    dim_c = build_dim_customer(rfm, orders)
    dim_cat = build_dim_category(fact)
    dim_d = build_dim_date()
    coh = build_cohort(ret)

    checks_python(fact, dim_c, dim_cat, dim_d, coh)
    if not no_sql:
        checks_sql(fact, dim_c, dim_cat)
    assert not FAILS, f"Не прошли проверки: {FAILS}. CSV не записаны."

    kw = dict(index=False, date_format="%Y-%m-%d", float_format="%.2f")
    for name, df in [("fact_sales", fact), ("dim_customer", dim_c), ("dim_category", dim_cat),
                     ("dim_date", dim_d), ("agg_cohort_retention", coh)]:
        path = OUT / f"{name}.csv"
        df.to_csv(path, **kw)
        print(f"  → {path}: {len(df):,} строк, {len(df.columns)} колонок, {path.stat().st_size/1e6:.1f} МБ")
    print("\nВсе проверки пройдены, CSV записаны.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sql", action="store_true", help="пропустить сверку с PostgreSQL")
    main(ap.parse_args().no_sql)