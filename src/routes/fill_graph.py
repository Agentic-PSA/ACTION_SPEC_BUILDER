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
from src.services.fill_graph import fill_graph_single_core, convert_units, process_specification, apply_changes







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
    output_dir = create_output_directory()
    data = await request.json()  # wejście np. lista lub jakieś parametry
    file = data["file"]
    results = []

    file_path = f"database/pim_by_type/{file}"
    _, ext = os.path.splitext(file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        if ext == ".jsonl":
            pim_list = [json.loads(line) for line in f if line.strip()]  # każda linia to osobny JSON
        elif ext == ".json":
            pim_list = json.load(f).get("pim", [])
        print(f"Wczytano {len(pim_list)} elementów z pliku {file}")

    # start_index = 0
    # count = 1
    # end_index = start_index + count
    # for idx, pim_data in enumerate(pim_list[start_index:end_index], start=start_index):
    for idx, pim_data in enumerate(pim_list):
        print(f"\n--- Przetwarzanie obiektu {idx + 1}/{len(pim_list)} ---")
        # można tu zrobić drobną wstępną weryfikację
        if not pim_data['body'].get('BarcodeCollection'):
            print(f"Brak EAN dla ProductNumber: {pim_data['body'].get('ProductNumber')}")
            continue

        # wywołanie core
        output = await fill_graph_single_core(pim_data)

        # dodanie do results
        results.append({
            "PIMProductId": pim_data['body'].get("PIMProductId"),
            "ean": pim_data['body']['BarcodeCollection'][0]['BarCode'],
            "output": output
        })

    return JSONResponse({
        "success": True,
        "count": len(results),
        "results": results
    })


async def fill_graph_single(request):
    pim_data = await request.json()
    output = await fill_graph_single_core(pim_data)
    return JSONResponse(output)