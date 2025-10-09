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

    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    data = await request.json()  # <- to zwraca dict

    # docelowo pobranie z szyny

    # ean = "8806087072013"
    # ean = "6942351406268"

    results = []

    with open("pim_by_type/Grzejniki.json", "r", encoding="utf-8") as f:
        # wczytanie całego pliku JSON
        pim_list = json.load(f).get("pim", [])
        print(f"Wczytano {len(pim_list)} elementów z pliku Telewizory.json")
    for iddx, pim_data in enumerate(pim_list):

        print(f"\n--- Przetwarzanie obiektu {iddx + 1}/{len(pim_list)} ---")
        ean_category = "AGD-GDU"
        connector = aiohttp.TCPConnector(limit=30)
        async with aiohttp.ClientSession(connector=connector) as session:
            if not len(pim_data['body']['BarcodeCollection']):
                print(f"Brak EAN dla ProductNumber: {pim_data['body'].get('ProductNumber', '')}")
                continue
            element = await send_message(session, "get_ean", pim_data['body']['BarcodeCollection'][0]['BarCode'])

            if not element or element.get("ean_response_is_empty", False):
                print(f"przeskok: {pim_data['body']['BarcodeCollection'][0]['BarCode']}")
                continue
            panel_data = element.get("panel_data", {})
            print(f"Przetwarzanie EAN: {panel_data.get('product_ean', '')} dla typu {ean_category}")
            specification, errors = process_specification(panel_data, ["PL"])
            spec_data = get_form_data('category', ean_category)

            translates = spec_data['translates']
            save_to_output_dir(specification, 'specification')

            specification = apply_changes(specification, translates)
            save_to_output_dir(specification, 'specification2')

            correct_values = spec_data['values_map']
            for i, section in enumerate(specification.get("PL", [])):
                attributes = section.get("attributes")
                if section['section_name'] in correct_values:
                    for key, value in attributes.items():
                        if key in correct_values[section['section_name']]:
                            for correct_key, correct_value in correct_values[section['section_name']][key][
                                'values'].items():
                                if value in correct_value:
                                    if correct_values[section['section_name']][key]['unit']:
                                        attributes[key] = correct_key + " " + correct_values[section['section_name']][key]['unit']
                                    else:
                                        attributes[key] = correct_key
                                    break

            numerical = {}

            for i, section in enumerate(specification.get("PL", [])):
                attributes = section.get("attributes")
                attributes_types = section.get("attributes_types")
                for key, value in attributes_types.items():
                    if value == "numerical":
                        numerical[key] = attributes[key]

            units = convert_units(numerical)
            for i, section in enumerate(specification.get("PL", [])):
                attributes = section.get("attributes")
                attributes_types = section.get("attributes_types")
                for key, value in attributes_types.items():
                    if value == "numerical" and key in units:
                        attributes[key] = units[key]
            for trans in pim_data.get('body', {}).get('TranslationCollection', []):
                lang = trans.get('Language', '').split('-')[0].upper() or 'un'
                product_name = trans.get('ProductName', '')
                product_desc = trans.get('ProductDescription', '')
                print(f"  Przetwarzanie tłumaczenia: {lang} - {product_name}")
                if lang not in ['pl', 'un']:
                    specification['common'][f'Name{lang}'] = product_name
                    print(f"    Dodano common Name{lang}: {product_name}")
                if lang == 'pl':
                    specification["common"]['Nazwa'] = product_name


                trans.update({
                    'ProductName': product_desc or '',
                })
                trans.pop('ProductDescription', None)

            add_nodes_data = {
                "type": ean_category,
                "properties": specification,
                "pim_data": pim_data['body']
            }
            try:
                async with session.post(
                        "http://172.16.10.3:30383/add_product",
                        json=add_nodes_data,
                        headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        results.append({
                            "ean": panel_data.get('product_ean', ''),
                            "status": "ok",
                            "response": result
                        })
                    else:
                        results.append({
                            "ean": panel_data.get('product_ean', ''),
                            "status": "error",
                            "code": response.status,
                            "details": await response.text()
                        })
            except Exception as e:
                logging.error(f"Błąd podczas komunikacji z API grafu: {str(e)}")
                results.append({
                    "ean": panel_data.get('product_ean', ''),
                    "status": "exception",
                    "error": str(e)
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