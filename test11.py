import pandas as pd
import psycopg2
from psycopg2 import sql
from datetime import datetime

# === KONFIGURACJA POŁĄCZENIA Z BAZĄ ===
DB_CONFIG = {
    "host": "172.16.10.3",
    "port": 30008,
    "database": "postgres",
    "user": "postgres",
    "password": "CQ15V1xNC9"
}

# === WCZYTANIE DANYCH Z EXCELA ===
excel_path = "data/drzewo z produktami.xlsx"

df = pd.read_excel(excel_path)

# === FILTRACJA ===
df = df[df["SalesChannelId"] == 1]

# === WYBÓR KOLUMN ===
columns = [
    "CategoryId_Level1", "CategoryName_Level1",
    "CategoryId_Level2", "CategoryName_Level2",
    "CategoryId_Level3", "CategoryName_Level3"
]

df = df[columns]

# === USUNIĘCIE DUPLIKATÓW WZGLĘDEM CategoryId_Level3 ===
df = df.drop_duplicates(subset=["CategoryId_Level3"])

# === DODANIE DATY AKTUALIZACJI ===
df["update_date"] = datetime.now()
print(df.head())
# === POŁĄCZENIE Z BAZĄ ===
conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()

# === UTWORZENIE TABELI JEŚLI NIE ISTNIEJE ===
create_table_query = """
CREATE TABLE IF NOT EXISTS iserwis_categories (
    CategoryId_Level1 TEXT,
    CategoryName_Level1 TEXT,
    CategoryId_Level2 TEXT,
    CategoryName_Level2 TEXT,
    CategoryId_Level3 TEXT PRIMARY KEY,
    CategoryName_Level3 TEXT,
    update_date TIMESTAMP
);
"""
cursor.execute(create_table_query)
conn.commit()

# === WSTAWIANIE DANYCH ===
insert_query = sql.SQL("""
    INSERT INTO iserwis_categories (
        CategoryId_Level1, CategoryName_Level1,
        CategoryId_Level2, CategoryName_Level2,
        CategoryId_Level3, CategoryName_Level3,
        update_date
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (CategoryId_Level3)
    DO UPDATE SET
        CategoryName_Level1 = EXCLUDED.CategoryName_Level1,
        CategoryName_Level2 = EXCLUDED.CategoryName_Level2,
        CategoryName_Level3 = EXCLUDED.CategoryName_Level3,
        update_date = EXCLUDED.update_date;
""")

for _, row in df.iterrows():
    print(row)
    cursor.execute(insert_query, (
        row["CategoryId_Level1"],
        row["CategoryName_Level1"],
        row["CategoryId_Level2"],
        row["CategoryName_Level2"],
        row["CategoryId_Level3"],
        row["CategoryName_Level3"],
        row["update_date"]
    ))

conn.commit()
cursor.close()
conn.close()

print(f"✅ Załadowano {len(df)} unikalnych kategorii (SalesChannelId=1) do tabeli 'iserwis_categories'")
