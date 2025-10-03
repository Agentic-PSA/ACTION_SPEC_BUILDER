# src/services/db_service.py
import os
import json
import psycopg2

def form_save(categories, llm_form, form, form_with_values, translates, form_categories):
    # połączenie
    conn_params = {
        "dbname": "postgres",
        "user": "postgres",
        "password": "CQ15V1xNC9",
        "host": "172.16.10.3",
        "port": 30008
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
            for category in categories:
                cur.execute(
                    query,
                    (
                        category,
                        json.dumps(form, ensure_ascii=False),
                        json.dumps(form_with_values, ensure_ascii=False),
                        json.dumps(translates, ensure_ascii=False),
                        json.dumps(llm_form, ensure_ascii=False),
                        json.dumps(form_categories, ensure_ascii=False)            
                    )
                )

    