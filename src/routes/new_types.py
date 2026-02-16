import datetime
import json
import logging
import os
import re

import aiohttp
import psycopg2
from pint import UnitRegistry
from psycopg2 import extras, sql
from starlette.responses import JSONResponse

from src.services.ean_service import send_message
from src.services.file_service import save_json_file
from src.services.fill_graph import fill_graph_single_core, convert_units, process_specification, apply_changes, check_quantity
from .etl2 import load_category_types
from src.services.db_service import get_all_categories



async def new_types(request):
    categories = get_all_categories()
    for category in categories:
        descr = f"{category["type"]} ({category["category"]})"
        print(descr)

        # 1. Spłaszcz dane: połącz wszystkie kategorie w jedną listę (parametr, wartość)
        flattened = []
        for section, params in category["product_params_cnt"].items():
            for param, value in params.items():
                flattened.append((section, param, value))

        # 2. Posortuj po wartości malejąco
        flattened.sort(key=lambda x: x[2], reverse=True)

        # 3. Weź 10 pierwszych
        top_10 = flattened[:10]

        grouped = {}
        for section, param, value in top_10:
            if section not in grouped:
                grouped[section] = []
            grouped[section].append(param)

        # wyświetlenie
        for section, items in grouped.items():
            params_text = ", ".join(items)
            descr += f"\n{section}: {params_text}"
        add_nodes_data = {"name":descr, "code":category["category"], "specification":category["form"]}
        try:
            async with aiohttp.request(
                "POST",
                f"http://{os.environ.get('NEO_RETRIEVER_URL')}/add_type",
                json=add_nodes_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                resp_ok = response.status == 200
                resp_content = await response.json() if resp_ok else await response.text()
        except Exception as e:
            resp_ok = False
            resp_content = str(e)
        print("add_type", resp_ok)

    return JSONResponse({
        "success": True
    })


