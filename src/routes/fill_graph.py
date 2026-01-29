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
from src.services.db_service import get_forms


async def should_skip_category(category_type: str, force: bool) -> bool:
    #sprawdź czy jest formatka
    forms = get_forms(category_type)
    if not forms or not forms.get("values_map"):
        return True

    # sprawdź czy są już wpisy w memgrafie
    if force:
        return False
    
    quantity_resp = await check_quantity(category_type)
    if not quantity_resp or not quantity_resp.get("success"):
        print(f"Error pobierania liczby produktów dla {category_type}: {quantity_resp.get('error') if quantity_resp else 'Brak odpowiedzi'}")
        return True

    print(f"Jest {quantity_resp.get('cnt', 0)} produktów w {category_type}")
    return quantity_resp.get("cnt", 0) > 0

def create_output_directory():
    """
    Tworzy folder wyjściowy na podstawie bieżącej daty i godziny.

    Returns:
        str: Ścieżka do utworzonego katalogu
    """
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = os.path.join("output3", timestamp)

    # Tworzenie katalogu, jeśli nie istnieje
    os.makedirs(output_dir, exist_ok=True)

    print(f"Utworzono katalog wyjściowy: {output_dir}")
    return output_dir


async def fill_graph(request):
    data = await request.json()  # wejście np. lista lub jakieś parametry
    category_types = load_category_types(data["type"])
    results = []
    ok = 0
    fail = 0

    for category_type in category_types:
        # nazwa kategorii dla llma
        product_type = category_type.replace("_", " ")
        # jeśli nie ma formatki lub są już dane w bazie to pomijamy
        print(f"Sprawdzam {category_type} zmienione na {product_type}")
        if await should_skip_category(product_type, data["force"]):
            print(f"Pomijam {product_type}")
            continue
        print(f"-------------> Pracuję {product_type}")
        file_path = f"database/pim_by_type/{category_type}.jsonl"
        with open(file_path, "r", encoding="utf-8") as f:
            pim_list = [json.loads(line) for line in f if line.strip()]  # każda linia to osobny JSON
        print(f"Wczytano {len(pim_list)} elementów z pliku {category_type}.jsonl")

        # start_index = 0
        # count = 1
        # end_index = start_index + count
        # for idx, pim_data in enumerate(pim_list[start_index:end_index], start=start_index):
        for idx, pim_data in enumerate(pim_list):
            print(f"\n--- Przetwarzanie obiektu {idx + 1}/{len(pim_list)} ---")
            # można tu zrobić drobną wstępną weryfikację
            # if not pim_data['body'].get('BarcodeCollection'):
            #     print(f"Brak EAN dla ProductNumber: {pim_data['body'].get('ProductNumber')}")
            #     continue

            # wywołanie core
            output = await fill_graph_single_core(pim_data)
            if output.get("ProductNumber"):
                ok += 1
            else:
                fail += 1

            # dodanie do results
            results.append(output)

    return JSONResponse({
        "success": True,
        "count": len(results),
        "ok": ok,
        "fail": fail
    })


async def fill_graph_single(request):
    pim_data = await request.json()
    output = await fill_graph_single_core(pim_data)
    return JSONResponse(output)