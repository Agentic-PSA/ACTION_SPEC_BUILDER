# src/services/db_service.py
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

def category_to_type(type, category):
    # połączenie
    conn_params = {
        "dbname": os.environ.get("POSTGRES_DB"),
        "user": os.environ.get("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD"),
        "host": os.environ.get("POSTGRES_HOST"),
        "port": os.environ.get("POSTGRES_PORT")
    }      
    query = """
        INSERT INTO category_to_type (type, category)
        VALUES(%s, %s)
        ON CONFLICT (type, category) DO NOTHING;
    """
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(
                query, (type, category)
            ) 
        conn.commit()   

def form_save(product_type, llm_form, form, form_with_values, translates, form_categories):
    # połączenie
    conn_params = {
        "dbname": os.environ.get("POSTGRES_DB"),
        "user": os.environ.get("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD"),
        "host": os.environ.get("POSTGRES_HOST"),
        "port": os.environ.get("POSTGRES_PORT")
    }    
    query = """
        INSERT INTO forms (category, form, form_with_values, translates, llm_form, categories)
        VALUES(%s, %s, %s, %s, %s, %s)
        ON CONFLICT (category) DO UPDATE
        SET 
            form = EXCLUDED.form, 
            form_with_values = EXCLUDED.form_with_values, 
            translates = EXCLUDED.translates, 
            llm_form = EXCLUDED.llm_form, 
            categories = EXCLUDED.categories
    """

    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    product_type,
                    json.dumps(form, ensure_ascii=False),
                    json.dumps(form_with_values, ensure_ascii=False),
                    json.dumps(translates, ensure_ascii=False),
                    json.dumps(llm_form, ensure_ascii=False),
                    json.dumps(form_categories, ensure_ascii=False)            
                )
            )
        conn.commit()

def get_category_by_id(category_id):
    conn_params = {
        "dbname": os.environ.get("POSTGRES_DB"),
        "user": os.environ.get("POSTGRES_USER"),
        "password": os.environ.get("POSTGRES_PASSWORD"),
        "host": os.environ.get("POSTGRES_HOST"),
        "port": os.environ.get("POSTGRES_PORT")
    }  
    query = """
        SELECT *
        FROM iserwis_categories
        WHERE categoryid_level3 = %s;
    """
    with psycopg2.connect(**conn_params) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (str(category_id),))
            category = cur.fetchone()

        if category:
            return category

        category_from_api = get_category_tree(category_id)
        if not category_from_api:
            return None

        categories = {item["categoryId"]: item for item in category_from_api}
        rows = []
        for cat in category_from_api:
            path = []
            current = cat
            while current:
                path.append(current)
                parent_id = current["parentCategoryId"]
                current = categories.get(parent_id)
            path.reverse()

            row = {}
            for i, level in enumerate(path, start=1):
                row[f"categoryid_level{i}"] = level["categoryId"]
                row[f"categoryname_level{i}"] = level["name"]
            rows.append(row)

        row = next((r for r in rows if r.get("categoryid_level3") == category_id), None)
        if not row:
            return None

        query_insert = """
            INSERT INTO iserwis_categories (
                categoryid_level1, categoryname_level1,
                categoryid_level2, categoryname_level2,
                categoryid_level3, categoryname_level3,
                update_date
            )
            VALUES(%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (categoryid_level3) DO NOTHING
            RETURNING *;
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                query_insert, (
                    row.get("categoryid_level1"),
                    row.get("categoryname_level1"),
                    row.get("categoryid_level2"),
                    row.get("categoryname_level2"),
                    row.get("categoryid_level3"),
                    row.get("categoryname_level3")
                )
            )
            inserted = cur.fetchone()
            conn.commit()

        return inserted or row

def get_category_tree(category_id: int):
    url = f"https://api-int-dev.action.pl/api/1.0/Pim/Categories/{category_id}/Hierarchy"
    headers = {
        'ApiKey': 'aksdgjhKSJFHLkjdsfhfkdjhKLJSHDFf'
    }

    response = requests.get(url, headers=headers)
    return response.json().get("data")
