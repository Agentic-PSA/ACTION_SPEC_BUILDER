# src/services/db_service.py
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

conn_params = {
    "dbname": os.environ.get("POSTGRES_DB"),
    "user": os.environ.get("POSTGRES_USER"),
    "password": os.environ.get("POSTGRES_PASSWORD"),
    "host": os.environ.get("POSTGRES_HOST"),
    "port": os.environ.get("POSTGRES_PORT")
}

def get_connection():
    try:
        return psycopg2.connect(**conn_params)
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return None

def db_select(query, params=(), fetchone=False):
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return None

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone() if fetchone else cur.fetchall()
    except Exception as e:
        print(f"DB SELECT error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def db_execute(query, params=()):
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        with conn.cursor() as cur:
            cur.execute(query, params)

        conn.commit()
        return True
    except Exception as e:
        print(f"DB EXECUTE error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def db_insert_returning(query, params=()):
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return None

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()

        conn.commit()
        return row
    except Exception as e:
        print(f"DB INSERT RETURNING error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_forms(categories_type):
    return db_select(
        "SELECT * FROM forms WHERE category = %s;",
        (str(categories_type),),
        fetchone=True
    )

def get_categories_in_type(categories_type):
    return db_select(
        "SELECT * FROM category_to_type WHERE type = %s;",
        (str(categories_type),)
    ) or []

def add_excludes_to_search(category, excludes):
    return db_execute(
        """
        UPDATE category_to_type
        SET search_excludes = %s
        WHERE category = %s
        """,
        (json.dumps(excludes, ensure_ascii=False), str(category))
    )

def category_to_type(category_type, category):
    return db_execute(
        """
        INSERT INTO category_to_type (type, category)
        VALUES (%s, %s)
        ON CONFLICT (type, category) DO NOTHING;
        """,
        (category_type, category)
    )

def form_save(product_type, llm_form, form, form_with_values, translates, form_categories, to_remove, product_params_cnt, main_data, items):
    return db_execute(
        """
        INSERT INTO forms (category, form, form_with_values, translates, llm_form, categories, to_remove, product_params_cnt, main_data, items)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (category) DO UPDATE SET
            form = EXCLUDED.form,
            form_with_values = EXCLUDED.form_with_values,
            translates = EXCLUDED.translates,
            llm_form = EXCLUDED.llm_form,
            categories = EXCLUDED.categories,
            to_remove = EXCLUDED.to_remove,
            product_params_cnt = EXCLUDED.product_params_cnt,
            main_data = EXCLUDED.main_data;
        """,
        (
            product_type,
            json.dumps(form, ensure_ascii=False),
            json.dumps(form_with_values, ensure_ascii=False),
            json.dumps(translates, ensure_ascii=False),
            json.dumps(llm_form, ensure_ascii=False),
            json.dumps(form_categories, ensure_ascii=False),
            json.dumps(to_remove, ensure_ascii=False),
            json.dumps(product_params_cnt, ensure_ascii=False),
            json.dumps(main_data, ensure_ascii=False),
            items
        )
    )

def get_category_by_id(category_id):
    # 1. Spróbuj z DB
    row = db_select(
        "SELECT * FROM iserwis_categories WHERE categoryid_level3 = %s;",
        (str(category_id),),
        fetchone=True
    )
    if row:
        return row

    # 2. Pobierz z API
    tree = get_category_tree(category_id)
    if not tree:
        return None

    # zbudowanie mapy Parent -> Child
    categories = {item["categoryId"]: item for item in tree}
    rows = []

    for item in tree:
        path = []
        current = item
        while current:
            path.append(current)
            current = categories.get(current["parentCategoryId"])
        path.reverse()

        row = {}
        for i, level in enumerate(path, start=1):
            row[f"categoryid_level{i}"] = level["categoryId"]
            row[f"categoryname_level{i}"] = level["name"]
        rows.append(row)

    final = next((r for r in rows if r.get("categoryid_level3") == category_id), None)
    if not final:
        return None

    # 3. Wstaw do bazy
    inserted = db_insert_returning(
        """
        INSERT INTO iserwis_categories (
            categoryid_level1, categoryname_level1,
            categoryid_level2, categoryname_level2,
            categoryid_level3, categoryname_level3,
            update_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (categoryid_level3) DO NOTHING
        RETURNING *;
        """,
        (
            final.get("categoryid_level1"),
            final.get("categoryname_level1"),
            final.get("categoryid_level2"),
            final.get("categoryname_level2"),
            final.get("categoryid_level3"),
            final.get("categoryname_level3")
        )
    )

    return inserted or final

def get_category_tree(category_id: int):
    url = f"https://api-int-dev.action.pl/api/1.0/Pim/Categories/{category_id}/Hierarchy"
    headers = {
        'ApiKey': 'aksdgjhKSJFHLkjdsfhfkdjhKLJSHDFf'
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
    except requests.exceptions.RequestException as e:
        print(f"API request error: {e}")
        return None

    if response.status_code != 200:
        print(f"API returned {response.status_code}")
        return None

    try:
        data = response.json().get("data") or []
    except Exception as e:
        print(f"Error parsing API JSON: {e}")
        return None

    return data

def get_all_categories():
    return db_select("SELECT ct.type, ct.category, f.product_params_cnt, f.form FROM category_to_type ct, forms f where ct.type=f.category") or []

