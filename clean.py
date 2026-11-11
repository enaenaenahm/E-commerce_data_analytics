"""
src/clean.py — очистка Olist и сохранение в data/processed/.

Принципы:
  * ничего не выдумываем и не удаляем «на всякий случай»;
  * каждое правило логируем (сколько строк затронуто);
  * в конце сверяем выручку с цифрами аудита (этап 1).
"""
from pathlib import Path
import pandas as pd

RAW = Path("data")
OUT = Path("data/processed")
OUT.mkdir(parents=True, exist_ok=True)

# Контрольные суммы из аудита (delivered-заказы)
EXPECTED_PRICE = 13_221_498.11
EXPECTED_PRICE_FREIGHT = 15_419_773.75

# Предварительный период анализа (подтвердим по распределению заказов по месяцам)
ANALYSIS_START, ANALYSIS_END = "2017-01-01", "2018-08-31"

# Две категории, которых нет в файле перевода
MANUAL_TRANSLATION = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_preparers",
}

log = []  # список строк для лога очистки


def note(msg: str) -> None:
    print(msg)
    log.append(msg)


def load_raw() -> dict[str, pd.DataFrame]:
    files = {
        "customers": "olist_customers_dataset.csv",
        "orders": "olist_orders_dataset.csv",
        "items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "products": "olist_products_dataset.csv",
        "translation": "product_category_name_translation.csv",
    }
    return {k: pd.read_csv(RAW / v) for k, v in files.items()}


def clean_orders(orders: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    df = orders.copy()

    # Защитная дедупликация по ключу
    n = len(df)
    df = df.drop_duplicates("order_id")
    note(f"orders: удалено дублей order_id: {n - len(df)}")

    # Даты -> datetime
    date_cols = [c for c in df.columns if c.endswith(("_timestamp", "_date", "_at"))]
    df[date_cols] = df[date_cols].apply(pd.to_datetime, errors="coerce")

    # Статус: единый регистр, без пробелов
    df["order_status"] = df["order_status"].str.strip().str.lower()

    # customer_id уникален на заказ -> для retention/RFM берём customer_unique_id
    df = df.merge(
        customers[["customer_id", "customer_unique_id"]],
        on="customer_id", how="left", validate="m:1",
    )
    note(f"orders: без customer_unique_id: {df.customer_unique_id.isna().sum()}")

    # Флаги вместо удаления строк
    df["is_delivered"] = df["order_status"].eq("delivered")
    df["is_canceled"] = df["order_status"].isin(["canceled", "unavailable"])
    df["purchase_month"] = df["order_purchase_timestamp"].dt.to_period("M").dt.to_timestamp()
    df["in_analysis_period"] = df["order_purchase_timestamp"].between(
        ANALYSIS_START, pd.Timestamp(ANALYSIS_END) + pd.Timedelta(days=1), inclusive="left"
    )
    # delivered без даты доставки: оставляем, но помечаем (для метрик сроков)
    df["delivery_date_missing"] = df.is_delivered & df.order_delivered_customer_date.isna()
    note(f"orders: delivered без даты доставки (оставлены, помечены): "
         f"{df.delivery_date_missing.sum()}")
    return df


def clean_products(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    tr = dict(zip(translation.product_category_name,
                  translation.product_category_name_english))
    tr.update(MANUAL_TRANSLATION)

    df = products[["product_id", "product_category_name"]].drop_duplicates("product_id").copy()
    df["category_pt"] = df.product_category_name.str.strip().str.lower()
    df["category_en"] = df.category_pt.map(tr)

    # Пропуски категорий -> 'unknown' (выручку не теряем)
    miss = df.category_en.isna().sum()
    df["category_en"] = df.category_en.fillna("unknown")
    df["category_pt"] = df.category_pt.fillna("unknown")
    note(f"products: товаров без категории/перевода -> 'unknown': {miss}")
    return df.drop(columns="product_category_name")


def clean_items(items: pd.DataFrame, orders: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    df = items.copy()
    n = len(df)
    df = df.drop_duplicates(["order_id", "order_item_id"])
    note(f"items: удалено дублей (order_id, order_item_id): {n - len(df)}")

    # Некорректные суммы: фиксируем и исключаем только явный мусор
    bad = (df.price <= 0) | (df.freight_value < 0)
    note(f"items: строк с price<=0 или freight<0 (исключены): {bad.sum()}")
    df = df[~bad]

    # Присоединяем статус/клиента/дату и категорию
    df = df.merge(
        orders[["order_id", "customer_unique_id", "order_status",
                "order_purchase_timestamp", "purchase_month", "in_analysis_period"]],
        on="order_id", how="inner", validate="m:1",
    )
    df = df.merge(products[["product_id", "category_en"]], on="product_id", how="left")
    df["category_en"] = df.category_en.fillna("unknown")  # товар не найден в products
    df["line_revenue"] = df["price"]  # Revenue = price (без доставки)
    return df


def clean_payments(pay: pd.DataFrame) -> pd.DataFrame:
    df = pay.copy()
    bad = df.payment_value <= 0
    note(f"payments: строк с payment_value<=0 (оставлены, только для сверки): {bad.sum()}")
    return df


def reconcile(items: pd.DataFrame) -> None:
    """Сверка с аудитом: delivered, до фильтра по периоду."""
    d = items[items.order_status == "delivered"]
    price, pf = d.price.sum(), (d.price + d.freight_value).sum()
    note(f"CHECK SUM(price) delivered = {price:,.2f} (ожидалось {EXPECTED_PRICE:,.2f})")
    note(f"CHECK price+freight       = {pf:,.2f} (ожидалось {EXPECTED_PRICE_FREIGHT:,.2f})")
    # Допуск 1 цент: расхождение означало бы, что мы потеряли/задвоили строки
    assert abs(price - EXPECTED_PRICE) < 0.01, "Revenue не совпала с аудитом!"
    assert abs(pf - EXPECTED_PRICE_FREIGHT) < 0.01, "Price+freight не совпали с аудитом!"


def main() -> None:
    raw = load_raw()
    orders = clean_orders(raw["orders"], raw["customers"])
    products = clean_products(raw["products"], raw["translation"])
    items = clean_items(raw["items"], orders, products)
    payments = clean_payments(raw["payments"])

    reconcile(items)

    # Диагностика, о которой просили в аудите
    note("\nСтатусы заказов:\n" + orders.order_status.value_counts().to_string())
    no_items = orders[~orders.order_id.isin(items.order_id)]
    note("\nСтатусы 775 заказов без позиций:\n" +
         no_items.order_status.value_counts().to_string())
    note("\nЗаказов по месяцам (delivered):\n" +
         orders[orders.is_delivered].groupby("purchase_month").size().to_string())

    # Сохранение
    orders.to_csv(OUT / "orders.csv", index=False)
    items.to_csv(OUT / "order_items.csv", index=False)
    products.to_csv(OUT / "products.csv", index=False)
    payments.to_csv(OUT / "payments.csv", index=False)
    (OUT / "cleaning_log.txt").write_text("\n".join(log), encoding="utf-8")
    note(f"\nСохранено в {OUT}: orders={len(orders)}, items={len(items)}, "
         f"products={len(products)}, payments={len(payments)}")


if __name__ == "__main__":
    main()