import json
import logging
import re
import os
import aiohttp
import psycopg2
from pint import UnitRegistry
from psycopg2 import extras, sql
from starlette.responses import JSONResponse
from src.services.db_service import get_category_by_id

from src.services.ean_service import send_message, send_message_by_action

ureg = UnitRegistry()
ureg.define("dni = day")
ureg.define("lat = year")
ureg.define("szt = []")
Q_ = ureg.Quantity

PIKTOGRAMY = {
    851070: "Substancje łatwopalne",
    851071: "Substancje pod ciśnieniem",
    851072: "Drażniące lub szkodliwe",
    851073: "Korozja",
    851074: "Zagrożenie dla środowiska",
    851075: "Poważne zagrożenie dla zdrowia",
    851082: "Toksyczne dla zdrowia",
    851103: "Materiały wybuchowe",
    831752: "GHS01: Substancje wybuchowe",
    830908: "GHS02: Flammable",
    831754: "GHS03: Substancje utleniające",
    831753: "GHS04: Gazy pod ciśnieniem",
    830057: "GHS05: Corrosive",
    831755: "GHS06: Toxic",
    807686: "GHS07: Szkodliwy"
}

def convert_units(numerical: dict) -> dict:
    #print(json.dumps(numerical, ensure_ascii=False, indent=4))
    response = {}
    for key, value in numerical.items():
        if isinstance(value, list):
            value = value[0]
        value = value.replace(",", ".", 1)
        match = re.search(r'(\d+(?:\.\d+)?)(\")?', value)
        if match and match.group(2) == '"':
            value = value.replace('"', ' in', 1)
        num_match = re.search(r'[-+]?\d+(?:\.\d+)?', value)
        unit_match = re.search(r'[^\d\.\s]+', value)
        if not num_match:
            response[key] = {
                'value': value,
                'unit': ""
            }
            continue

        num_str = num_match.group(0)
        try:
            if '.' in num_str:
                num = float(num_str)
            else:
                num = int(num_str)
        except ValueError:
            num = num_str
        unit2 = unit_match.group(0) if unit_match else ""

        try:
            # Jeśli °C lub °F – pomijamy Pint
            if "°C" in value or "oC" in value:
                num = float(re.search(r'[-+]?\d+(?:\.\d+)?', value).group(0))
                response[key] = {'value': num, 'unit': '°C'}
                continue
            elif "°F" in value:
                num = float(re.search(r'[-+]?\d+(?:\.\d+)?', value).group(0))
                response[key] = {'value': num, 'unit': '°F'}
                continue
            elif "\"" in value:
                num = float(re.search(r'[-+]?\d+(?:\.\d+)?', value).group(0))
                response[key] = {'value': num, 'unit': '"'}
                continue

            # Wszystko inne normalnie przez Pint
            # q = Q_(value)
            # v = q.to_base_units().magnitude  # wartości w jednostkach bazowych
            # u = q.to_base_units().units
            # response[key] = {'value': v, 'unit': f"{u:~}"}
            response[key] = {'value': num, 'unit': unit2}
        except Exception as e:
            logging.warning(f"Error processing {key}: {e}")

    #print(json.dumps(response, ensure_ascii=False, indent=4))
    return response



ALLOWED_COLUMNS = ["category", "categoryid_level3"]


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


def get_pg_data(column: str, value: str, table: str='forms') -> dict:
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
                host=os.environ.get("POSTGRES_HOST"),
                port=os.environ.get("POSTGRES_PORT"),
                database=os.environ.get("POSTGRES_DB"),
                user=os.environ.get("POSTGRES_USER"),
                password=os.environ.get("POSTGRES_PASSWORD")
        ) as conn:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cursor:
                query = sql.SQL("SELECT * FROM {forms} WHERE {field} = %s LIMIT 1").format(
                    field=sql.Identifier(column), forms=sql.Identifier(table)
                )
                cursor.execute(query, [value])
                result = cursor.fetchone()

                if not result:
                    raise ValueError(f"Brak danych w tabeli {table} dla {column} = '{value}'")

                return dict(result)

    except Exception as e:
        print(f"Błąd podczas pobierania danych z bazy: {e}")
        raise


async def fill_graph_single_core(pim_data):
    """
    Core logika fill_graph_single.
    Wejście: pim_data (dict) – to samo, co body requestu.
    Zwraca: dict z output.
    """

    ean_category = []
    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        action = pim_data['body'].get('ProductNumber', '')
        if action:
            element = await send_message_by_action(session, "get_action", action)

        if not element or element.get("ean_response_is_empty", False):
            if not len(pim_data['body'].get('BarcodeCollection', [])):
                return {
                    "success": False,
                    "error": f"Brak EAN dla ProductNumber: {pim_data['body'].get('ProductNumber', '')}"
                }
            element = await send_message(session, "get_ean", pim_data['body']['BarcodeCollection'][0]['BarCode'])

        if not element or element.get("ean_response_is_empty", False):
            return {
                "success": False,
                "error": f"Brak danych dla EAN: {pim_data['body']['BarcodeCollection'][0]['BarCode']}"
            }

        if not "CategoryMapCollection" in pim_data['body'] or not len(pim_data['body']['CategoryMapCollection']):
            return {
                "success": False,
                "error": f"Brak CategoryMapCollection dla ProductNumber: {pim_data['body'].get('ProductNumber', '')}"
            }
        # pobieramy tylko ID
        category_ids = {category.get("CategoryId") for cat in pim_data['body']['CategoryMapCollection']
                        if cat.get("SalesChannelId", 0) == 1
                        for category in cat.get("CategoryCollection", [])}
        # konwertujemy ID na nazwy level3
        # nie chcemy samego liscia
        # level3_names = [get_category_by_id(cat)['categoryname_level3'] for cat in category_ids if cat and cat != "0"]

        # konwertujemy ID na level2 / level3
        level2_3_names = [
            get_category_by_id(cat)['categoryname_level2'] + " / " + get_category_by_id(cat)['categoryname_level3']
            for cat in category_ids if cat and cat != "0"]

        # łączymy wynik
        # ean_category = level3_names + level2_3_names
        ean_category = level2_3_names

        ean_type = pim_data['body'].get("ProductType", "")
        panel_data = element.get("panel_data", {})
        specification, errors = process_specification(panel_data, ["PL"])
        spec_data = get_pg_data('category', ean_type)
        translates = spec_data['translates']
        # with open(f"aaa1_tr1_before.json", "w", encoding="utf-8") as f:
        #     json.dump(translates, f, ensure_ascii=False, indent=2)
        # translates["Konstrukcja"]["aka"] = "duda"
        # translates["Konstrukcja"]["aaa"] = "bbb"
        # translates["Zasilanie"]["aka"] = "duda"
        # translates["Chłodzenie"]["aaa"] = "bbb"
        # with open(f"aaa1_tr2_after.json", "w", encoding="utf-8") as f:
        #    json.dump(translates, f, ensure_ascii=False, indent=2)
        # specification["PL"][0]["attributes"]["aka"] = "aka_val"
        # specification["PL"][0]["attributes_types"]["aka"] = "dropdown"
        # specification["PL"][0]["attributes"]["duda"] = "duda_val"
        # specification["PL"][0]["attributes_types"]["duda"] = "dropdown"
        # specification["PL"][1]["attributes"]["aka"] = "aka3_val"
        # specification["PL"][1]["attributes_types"]["aka"] = "dropdown"
        # specification["PL"][3]["attributes"]["aaa"] = "aaa_val"
        # specification["PL"][3]["attributes_types"]["aaa"] = "dropdown"
        # with open(f"aaa1_before.json", "w", encoding="utf-8") as f:
        #     json.dump(specification, f, ensure_ascii=False, indent=2)
        specification = apply_changes(specification, translates)
        # with open(f"aaa2_after.json", "w", encoding="utf-8") as f:
        #     json.dump(specification, f, ensure_ascii=False, indent=2)
        # exit()
        correct_values = spec_data['values_map']
        for section in specification.get("PL", []):
            attributes = section.get("attributes")
            attributes_types = section.get("attributes_types", {})  # dodaj dla bezpieczeństwa
            if section['section_name'] in correct_values:
                for key, value in attributes.items():
                    if key in correct_values[section['section_name']]:
                        for correct_key, correct_value in correct_values[section['section_name']][key][
                            'values'].items():
                            if value in correct_value:
                                unit = correct_values[section['section_name']][key]['unit']
                                if unit:
                                    if attributes_types.get(key) == "numerical":
                                        # numerical - zostaje stary format, bo potem konwersja jednostek
                                        attributes[key] = f"{correct_key} {unit}"
                                    else:
                                        # nie-numerical - zapis jako obiekt {value, unit}
                                        attributes[key] = {"value": correct_key, "unit": unit}
                                else:
                                    attributes[key] = correct_key
                                break
        numerical = {}
        for section in specification.get("PL", []):
            attributes = section.get("attributes")
            attributes_types = section.get("attributes_types")
            for key, value in attributes_types.items():
                if value == "numerical":
                    numerical[key] = attributes[key]
        #print(json.dumps(numerical, indent=1))
        units = convert_units(numerical)
        for section in specification.get("PL", []):
            attributes = section.get("attributes")
            attributes_types = section.get("attributes_types")
            for key, value in attributes_types.items():
                if value == "numerical" and key in units:
                    attributes[key] = units[key]

        for trans in pim_data.get('body', {}).get('TranslationCollection', []):
            lang = trans.get('Language', '').split('-')[0].upper() or 'un'
            product_name = trans.get('ProductName', '')
            product_desc = trans.get('ProductDescription', '')
            if lang not in ['PL', 'UN']:
                specification['common'][f'Name{lang}'] = product_name
            if lang == 'PL':
                specification['common']['Nazwa'] = product_name
            trans.update({'ProductName': product_desc or trans.get('ProductName', '')})
            trans.pop('ProductDescription', None)

        if "TranslationCollection" not in pim_data['body']:
            pim_data['body']['TranslationCollection'] = []
            specification['common']['Nazwa'] = pim_data['body']['Name']

        if "ProductVersion" not in pim_data['body']:
            pim_data['body']['ProductVersion'] = "1.0"

        specification['common']["ProductNumber"] = pim_data['body'].get('ProductNumber', '')

        # wysyłka do API grafu
        add_nodes_data = {
            "type": ean_type,
            "additional_types": ean_category,
            "properties": specification,
            "pim_data": pim_data['body']
        }
        # with open(f"aaa3_wynik_add.json", "w", encoding="utf-8") as f:
        #     json.dump(add_nodes_data, f, ensure_ascii=False, indent=2)

        try:
            async with session.post(
                    f"http://{os.environ.get('NEO_RETRIEVER_URL')}/add_product",
                    json=add_nodes_data,
                    headers={"Content-Type": "application/json"}
            ) as response:
                resp_ok = response.status == 200
                resp_content = await response.json() if resp_ok else await response.text()
                if not resp_ok:
                    return {
                        "success": False,
                        "error": f"Status != 200: {pim_data['body'].get('ProductNumber', '')} - {resp_content}"
                    }

        except Exception as e:
            logging.error(f"Błąd podczas komunikacji z API grafu: {str(e)}")
            resp_ok = False
            resp_content = str(e)
            return {
                "success": False,
                "error": f"Błąd podczas komunikacji z API grafu: {pim_data['body'].get('ProductNumber', '')} - {resp_content}"
            }


        # konwersja specification na Speccollection
        speccollection = []
        for idx, section in enumerate(specification.get("PL", [])):
            attributes = section.get("attributes", {})
            for attr_idx, (key, value) in enumerate(attributes.items(), start=1):
                spec = {
                    "sectionId": idx + 1,
                    "atributeId": attr_idx,
                    "value": value['value'] if type(value) is dict else value,
                    "unit": value['unit'] if type(value) is dict and 'unit' in value else "",
                    "languageId": "pl"
                }

                speccollection.append(spec)

        output = {
            "ProductNumber": pim_data['body'].get("ProductNumber"),
            "PIMProductId": pim_data['body'].get("PIMProductId"),
            "Brand": pim_data['body'].get("Brand"),
            "CategoryMapCollection": pim_data['body'].get("CategoryMapCollection"),
            "ProductType": pim_data['body'].get("ProductType"),
            "NameEN": specification['common'].get("NameEN", pim_data['body'].get("Name", "") + " EN"),
            "NameDE": specification['common'].get("NameDE", pim_data['body'].get("Name", "") + " DE"),
            "TranslationCollection": pim_data['body'].get("TranslationCollection", []),
            "CNCode": pim_data['body'].get("CNCode"),
            "PKWiU": pim_data['body'].get("PKWiU"),
            "Intrastatname": pim_data['body'].get("Name", "") + " Intrastat",
            "IntrastatnameLong": pim_data['body'].get("Name", "") + " Intrastat Long",
            "CountryOfOrigin": pim_data['body'].get("CountryOfOrigin"),
            "Weight": pim_data['body'].get("Weight"),
            "Height": pim_data['body'].get("Height"),
            "Width": pim_data['body'].get("Width"),
            "Depth": pim_data['body'].get("Depth"),
            "Piktograms": [PIKTOGRAMY[851074], PIKTOGRAMY[830908]],
            "EnergyLabel": pim_data['body'].get("EnergyLabel"),
            "Battery100Wh": pim_data['body'].get("Battery100Wh"),
            "InstalledBattery": pim_data['body'].get("InstalledBattery"),
            "LooseBattery": pim_data['body'].get("LooseBattery"),
            "Large": pim_data['body'].get("Large"),
            "ComponentCollection": pim_data['body'].get("ComponentCollection", []),
            "RelatedProductCollection": pim_data['body'].get("RelatedProductCollection", []),
            "Speccollection": speccollection,
            "Photocollection": pim_data['body'].get("Photocollection", [])
        }

        return output


def apply_changes(data, changes):
    sections = data.get("PL", [])
    sections_map = {s["section_name"]: s for s in sections}

    removed_section = {
        "section_name": "Przeniesione",
        "attributes": {},
        "attributes_types": {}
    }

    for section in sections:
        section_name = section["section_name"]
        mapping = changes.get(section_name)

        # sekcja bez mapowań → nietknięta
        if not mapping:
            continue

        for old_attr in list(section["attributes"].keys()):
            if old_attr not in mapping:
                continue

            old_val = section["attributes"][old_attr]
            old_type = section["attributes_types"].get(old_attr)

            map_entry = mapping[old_attr]
            target_section_name = map_entry.get("section", section_name)
            new_attr = map_entry.get("param", old_attr)

            # print(
            #     f"MAP: {section_name}.{old_attr} "
            #     f"→ {target_section_name}.{new_attr} | value={old_val}"
            # )

            target_section = sections_map.get(target_section_name)
            if not target_section:
                # print(f"  CREATE SECTION: {target_section_name}")
                target_section = {
                    "section_name": target_section_name,
                    "section_sort": len(sections_map) + 1,
                    "attributes": {},
                    "attributes_types": {}
                }
                sections.append(target_section)
                sections_map[target_section_name] = target_section

            target_attrs = target_section["attributes"]
            target_types = target_section["attributes_types"]

            existing_val = target_attrs.get(new_attr)
            existing_type = target_types.get(new_attr)

            # konflikt
            if existing_val is not None:
                if old_type == "multi_dropdown" and existing_type == "multi_dropdown":
                    old_list = old_val if isinstance(old_val, list) else [old_val]
                    new_list = existing_val if isinstance(existing_val, list) else [existing_val]
                    combined = list(dict.fromkeys(new_list + old_list))
                    target_attrs[new_attr] = combined
                    target_types[new_attr] = old_type
                    # print(f"  MERGE multi_dropdown → {combined}")
                else:
                    removed_section["attributes"][old_attr] = old_val
                    if old_type:
                        removed_section["attributes_types"][old_attr] = old_type
                    # print(f"  CONFLICT → Przeniesione.{old_attr}")
            else:
                target_attrs[new_attr] = old_val
                if old_type:
                    target_types[new_attr] = old_type
                # print("  OK")

            # usuwamy tylko świadomie przeniesiony atrybut
            del section["attributes"][old_attr]
            section["attributes_types"].pop(old_attr, None)

    if removed_section["attributes"]:
        # print("ADD SECTION: Przeniesione")
        sections.append(removed_section)

    return data
