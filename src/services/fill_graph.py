import logging
import re

import aiohttp
import psycopg2
from pint import UnitRegistry
from psycopg2 import extras, sql

from src.services.ean_service import send_message

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
    """
    Przekształca wartości z jednostkami na postać ujednoliconą.

    Args:
        numerical (dict): np. {"length": "12,5cm", "height": "5\""}

    Returns:
        dict: {"length": {"value": 0.125, "unit": "m"}, "height": {"value": 0.127, "unit": "m"}}
    """
    response = {}
    for key, value in numerical.items():
        if type(value) is list:
            value = value[0]
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


async def fill_graph_single_core(pim_data):
    """
    Core logika fill_graph_single.
    Wejście: pim_data (dict) – to samo, co body requestu.
    Zwraca: dict z output.
    """

    ean_category = "AGD-GDU"
    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
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

        panel_data = element.get("panel_data", {})
        specification, errors = process_specification(panel_data, ["PL"])
        spec_data = get_form_data('category', ean_category)

        translates = spec_data['translates']
        specification = apply_changes(specification, translates)

        correct_values = spec_data['values_map']
        for section in specification.get("PL", []):
            attributes = section.get("attributes")
            if section['section_name'] in correct_values:
                for key, value in attributes.items():
                    if key in correct_values[section['section_name']]:
                        for correct_key, correct_value in correct_values[section['section_name']][key][
                            'values'].items():
                            if value in correct_value:
                                unit = correct_values[section['section_name']][key]['unit']
                                attributes[key] = f"{correct_key} {unit}" if unit else correct_key
                                break

        numerical = {}
        for section in specification.get("PL", []):
            attributes = section.get("attributes")
            attributes_types = section.get("attributes_types")
            for key, value in attributes_types.items():
                if value == "numerical":
                    numerical[key] = attributes[key]

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
            trans.update({'ProductName': product_desc or ''})
            trans.pop('ProductDescription', None)

        if "TranslationCollection" not in pim_data['body']:
            pim_data['body']['TranslationCollection'] = []
            specification['common']['Nazwa'] = pim_data['body']['Name']

        if "ProductVersion" not in pim_data['body']:
            pim_data['body']['ProductVersion'] = "1.0"

        # wysyłka do API grafu
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
                resp_ok = response.status == 200
                resp_content = await response.json() if resp_ok else await response.text()
        except Exception as e:
            logging.error(f"Błąd podczas komunikacji z API grafu: {str(e)}")
            resp_ok = False
            resp_content = str(e)

        # konwersja specification na Speccollection
        speccollection = []
        for idx, section in enumerate(specification.get("PL", [])):
            attributes = section.get("attributes", {})
            for attr_idx, (key, value) in enumerate(attributes.items(), start=1):
                speccollection.append({
                    "sectionId": idx + 1,
                    "atributeId": attr_idx,
                    "value": value,
                    "languageId": "pl"
                })

        output = {
            "PIMProductId": pim_data['body'].get("PIMProductId"),
            "Brand": pim_data['body'].get("Brand"),
            "CategoryMapCollection": pim_data['body'].get("CategoryMapCollection"),
            "ProductType": "",
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
    for section in data.get("PL", []):
        section_name = section["section_name"]

        # jeśli są mapowania dla tej sekcji
        if section_name in changes:
            mapping = changes[section_name]

            new_attributes = {}
            new_types = {}

            for attr, val in section["attributes"].items():
                # sprawdzamy czy attr jest w mapowaniu
                new_attr = mapping.get(attr, attr)
                if new_attr != attr:
                    print(f"Section '{section_name}': '{attr}' -> '{new_attr}'")
                new_attributes[new_attr] = val

                # poprawiamy też typ atrybutu
                if attr in section["attributes_types"]:
                    new_types[new_attr] = section["attributes_types"][attr]

            # podmieniamy całość
            section["attributes"] = new_attributes
            section["attributes_types"] = new_types

    return data
