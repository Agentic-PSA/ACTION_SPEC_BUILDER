# src/services/db_service.py
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

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

    return category
