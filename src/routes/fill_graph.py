import datetime
import json
import os
import psycopg2
from psycopg2 import extras, sql
from collections import Counter
import polars as pl
from starlette.responses import JSONResponse
from src.services.ean_service import read_eans, send_message
from src.services.ai_service import ask_gpt_custom, ask_sonoma_custom
from src.services.file_service import save_json_file
import aiohttp
import logging
import re
from pint import UnitRegistry

ureg = UnitRegistry()
Q_ = ureg.Quantity


def convert_units(numerical: dict) -> dict:
    """
    Przekształca wartości z jednostkami na postać ujednoliconą.

    Args:
        numerical (dict): np. {"length": "12,5cm", "height": "5\""}

    Returns:
        dict: {"length": {"value": 0.125, "unit": "m"}, "height": {"value": 0.127, "unit": "m"}}
    """
    response = {}
    for key, value in numerical.items():
        value = value.replace(",", ".", 1)
        match = re.search(r'(\d+(?:\.\d+)?)(\")?', value)
        if match and match.group(2) == '"':
            value = value.replace('"', ' in', 1)

        try:
            q = Q_(value)
            v = q.m  # wartość w jednostce bazowej
            u = q.u  # jednostka
            logging.debug(f"Processing {key}: value = {v}, unit = {u}")
            response[key] = {
                'value': v,
                'unit': f"{u:~}"
            }
        except Exception as e:
            logging.warning(f"Error processing {key}: {e}")

    return response


ALLOWED_COLUMNS = ["category"]


def process_specification(panel_data, specification_languages):
    panel_data_specification = panel_data.get("specification", [])
    specification = {}
    errors = []
    specification["EAN"] = panel_data.get("product_ean", "")
    specification["action"] = panel_data.get("product_dax_index", "")
    specification["common"] = {
        "Nazwa": panel_data.get("product_supplier_name", ""),
        "Product number": panel_data.get("product_part_number", ""),
        "Producent": panel_data.get("producer_name", "")
    }

    for lang in specification_languages:
        specification[lang] = []

    for section in panel_data_specification:
        section_name = section.get("section_name", {})
        section_name = {key: section_name[key] for key in specification_languages if key in section_name}
        section_sort = section.get("section_sort", 0)
        attributes = section.get("attributes", [])

        section_by_lang = {}
        for lang in specification_languages:
            section_by_lang[lang] = {
                "section_name": section_name[lang],
                "section_sort": section_sort,
                "attributes": {},
                "attributes_types": {}
            }

        for attribute in attributes:
            attribute_sort = attribute.get("attribute_sort", 0)
            attribute_type = attribute.get("attribute_type", "")
            attribute_name = attribute.get("attribute_name", {})
            attribute_name = {key: attribute_name[key] for key in specification_languages if key in attribute_name}
            values = attribute.get("values", [])
            if values:
                if len(values) == 1:
                    values = values[0].get("attribute_value_name", {})
                    values = {key: values[key] for key in specification_languages if key in values}
                else:
                    multiple_values = {key: [] for key in specification_languages}
                    for value in values:
                        attribute_value_name = value.get("attribute_value_name", {})
                        for lang in specification_languages:
                            if lang in attribute_value_name:
                                multiple_values[lang].append(attribute_value_name[lang])
                    values = multiple_values

            else:
                value = attribute.get("value", {})
                if value:
                    values = {key: value[key] for key in specification_languages if key in value}
                else:
                    errors.append(f"attribute_name: {attribute_name} , Values: {values}")
                    values = {}

            for lang in specification_languages:
                name = attribute_name.get(lang)
                value = values.get(lang)
                if name and value:
                    section_by_lang[lang]["attributes"][name] = value
                    section_by_lang[lang]["attributes_types"][name] = attribute_type
                else:
                    errors.append(f"name: {name}, value: {value}")

        for lang in specification_languages:
            specification[lang].append(section_by_lang[lang])
    return specification, errors


specification_languages = ["PL", "EN", "DE"]

def get_form_data(column: str, value: str) -> dict:
    """
    Pobiera dane formularza z bazy danych PostgreSQL dla podanej kolumny.

    Args:
        column (str): nazwa kolumny w tabeli forms
        value (str): wartość do wyszukania w kolumnie

    Returns:
        dict: rekord z tabeli forms jako słownik

    Raises:
        ValueError: jeśli nie znaleziono danych lub kolumna jest niedozwolona
        psycopg2.Error: w przypadku błędu połączenia lub zapytania
    """
    if column not in ALLOWED_COLUMNS:
        raise ValueError(f"Niedozwolona kolumna: {column}")

    try:
        with psycopg2.connect(
            host="172.16.10.3",
            port=30008,
            database="postgres",
            user="postgres",
            password="CQ15V1xNC9"
        ) as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
                query = sql.SQL("SELECT * FROM forms WHERE {field} = %s LIMIT 1").format(
                    field=sql.Identifier(column)
                )
                cursor.execute(query, [value])
                result = cursor.fetchone()

                if not result:
                    raise ValueError(f"Brak danych w tabeli forms dla {column} = '{value}'")

                return dict(result)

    except Exception as e:
        print(f"Błąd podczas pobierania danych z bazy: {e}")
        raise

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

    ean = "8806087072013"

    ean_category = "TVA-LCD"
    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        element = await send_message(session, "get_ean", ean)
        panel_data = element.get("panel_data", {})
        specification, errors = process_specification(panel_data, ["PL"])
        spec_data = get_form_data('category', ean_category)

        mapa_nazw_parametrów = spec_data['translates']


        #
        # TUTAJ PROCES PODMIANY PARAMETRÓW
        #
        # Wynik zwrócić do zmiennej specification

        correct_values = spec_data['values_map']
        for i, section in enumerate(specification.get("PL", [])):
            attributes = section.get("attributes")
            if section['section_name'] in correct_values:
                for key, value in attributes.items():
                    if key in correct_values[section['section_name']]:
                        for correct_key, correct_value in correct_values[section['section_name']][key]['values'].items():
                            if value in correct_value:
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
        add_nodes_data = {
            "type": ean_type,
            "properties": specification
        }
        # wywołanie "http://172.19.3.220:5013/add_product"
        return JSONResponse(specification)