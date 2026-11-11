"""
src/load_to_postgres.py — загрузка data/processed/*.csv в PostgreSQL через COPY
и сверка row counts / revenue между Python (pandas) и SQL.
"""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROCESSED = Path("data/processed")
SCHEMA_SQL = Path("sql/01_schema.sql")

DSN = "postgresql+psycopg2://{u}:{p}@{h}:{port}/{db}".format(
    u=os.getenv("PG_USER", "analyst"),
    p=os.getenv("PG_PASSWORD", "analyst_pwd"),
    h=os.getenv("PG_HOST", "localhost"),
    port=os.getenv("PG_PORT", "5432"),
    db=os.getenv("PG_DB", "ecommerce"),
)

# Порядок важен: сначала родительские таблицы (внешний ключ order_items -> orders)
TABLES = {
    "products": "products.csv",
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "payments": "payments.csv",
}


def copy_csv(conn, table: str, csv_path: Path) -> None:
    """Быстрая загрузка через COPY; список колонок берём из заголовка CSV."""
    cols = list(pd.read_csv(csv_path, nrows=0).columns)
    sql = f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, HEADER true)"
    raw = conn.connection  # psycopg2-соединение под SQLAlchemy
    with raw.cursor() as cur, open(csv_path, "r", encoding="utf-8") as f:
        cur.copy_expert(sql, f)


def main() -> None:
    engine = create_engine(DSN)

    # 1. Схема
    with engine.begin() as conn:
        conn.execute(text(SCHEMA_SQL.read_text(encoding="utf-8")))
        print("Схема создана.")

    # 2. Загрузка
    with engine.begin() as conn:
        for table, fname in TABLES.items():
            copy_csv(conn, table, PROCESSED / fname)
            print(f"Загружено: {table}")

    # 3. Сверка Python <-> SQL
    items = pd.read_csv(PROCESSED / "order_items.csv")
    delivered = items[items.order_status == "delivered"]
    py = {
        "products": len(pd.read_csv(PROCESSED / "products.csv")),
        "orders": len(pd.read_csv(PROCESSED / "orders.csv")),
        "order_items": len(items),
        "payments": len(pd.read_csv(PROCESSED / "payments.csv")),
        "revenue_delivered": round(delivered.price.sum(), 2),
        "orders_delivered": delivered.order_id.nunique(),
    }

    with engine.connect() as conn:
        sql = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in TABLES}
        sql["revenue_delivered"] = float(conn.execute(text(
            "SELECT ROUND(SUM(price), 2) FROM order_items WHERE order_status = 'delivered'"
        )).scalar())
        sql["orders_delivered"] = conn.execute(text(
            "SELECT COUNT(DISTINCT order_id) FROM order_items WHERE order_status = 'delivered'"
        )).scalar()

    print("\n{:<20}{:>18}{:>18}  OK?".format("метрика", "Python", "PostgreSQL"))
    ok_all = True
    for k in py:
        ok = abs(float(py[k]) - float(sql[k])) < 0.01
        ok_all &= ok
        print(f"{k:<20}{py[k]:>18,}{sql[k]:>18,}  {'✔' if ok else '✘'}")
    assert ok_all, "Python и PostgreSQL не совпали — смотри таблицу выше"
    print("\nВсе сверки пройдены.")


if __name__ == "__main__":
    main()