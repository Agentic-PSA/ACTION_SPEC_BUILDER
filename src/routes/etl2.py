# src/routes/etl2.py
from starlette.responses import JSONResponse
import aiohttp
import asyncio
import json
import os
import re
from src.services.ean_service import is_ean_valid, generate_ean_variants, send_message_with_fallback
from src.services.ai_service import ai_analyze_and_create_form, ai_add_main_data, ai_remove_duplicates, ai_set_order, ai_sugest_section_names, ai_remove_excess_sections, ai_analyze_and_create_form_new
from src.services.file_service import save_json_file
from src.services.form_service import build_form
from src.services.db_service import form_save, get_category_by_id, category_to_type, get_forms, get_categories_in_type, add_excludes_to_search
from .map_values import map_values_logic

import datetime
import os
import copy

def create_output_directory():
    """
    Tworzy folder wyjściowy na podstawie bieżącej daty i godziny.

    Returns:
        str: Ścieżka do utworzonego katalogu
    """
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = os.path.join("output", timestamp)

    # Tworzenie katalogu, jeśli nie istnieje
    os.makedirs(output_dir, exist_ok=True)

    print(f"Utworzono katalog wyjściowy: {output_dir}")
    return output_dir
# --------------------------------------------------------------------------------------------------------------

def add_truncated_sections(categories_type, save_to_output_dir):
    forms = get_forms(categories_type)
    categories = get_categories_in_type(categories_type)

    for category in categories:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Optymalizacja dla {category['category']} (AI)")
            filename = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', category['category'])
            excludes = ai_remove_excess_sections(category['category'], forms['llm_form'], f"optymalization_{filename}", save_to_output_dir)
            add_excludes_to_search(category['category'], excludes)
            save_to_output_dir(excludes, f"excludes_{filename}")
# --------------------------------------------------------------------------------------------------------------

async def process_single_ean(session, idx, total, k, v):
    single_spec = await send_message_with_fallback(v.get('action'), v.get('gtin_12'), v.get('gtin_13'), v.get('part_number'))
    if not single_spec:
        return None
    return {
        'panel': single_spec['panel_data'],
        'specification': single_spec['specification']
    }
# --------------------------------------------------------------------------------------------------------------


def load_data():
    with open("database/tmp_marged_products", "r", encoding="utf-8") as f:
        return json.load(f)
# --------------------------------------------------------------------------------------------------------------

def load_category_types(category_type):
    if isinstance(category_type, (list, tuple, set)):
        return list(category_type)

    if category_type == 'ALL':
        return [os.path.splitext(f)[0] for f in os.listdir("database/pim_by_type/") if f.endswith(".jsonl")]

    return [category_type]
# --------------------------------------------------------------------------------------------------------------

def load_pim_list(category_type):
    base_path = f"database/pim_by_type/{category_type}"
    pim_list = []

    for ext in [".jsonl", ".json"]:
        file_path = f"{base_path}{ext}"
        if not os.path.exists(file_path):
            print(f"Plik {file_path} nie istnieje, pomijam.")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            if ext == ".jsonl":
                pim_part = [json.loads(line) for line in f if line.strip()]
            elif ext == ".json":
                try:
                    data_json = json.load(f)
                    pim_part = data_json.get("pim", data_json if isinstance(data_json, list) else [])
                except json.JSONDecodeError as e:
                    print(f"Błąd dekodowania JSON w {file_path}: {e}")
                    pim_part = []
            pim_list.extend(pim_part)
            print(f"Wczytano {len(pim_part)} elementów z pliku {file_path}")
    return pim_list
# --------------------------------------------------------------------------------------------------------------

# wstępna weryfikacja danych wejściowych
def check_record(record, product_type):
    if not isinstance(record, dict):
        print("ERROR - pominięto rekord — nie jest słownikiem:", record)
        return False

    body = record.get("body") or {}
    if not isinstance(body, dict):
        print("ERROR - pominięto rekord — body to None lub nie dict")
        return False

    record_type = body.get("ProductType") or ''
    if record_type != product_type:
        print('ERROR - pominięto rekord — błędny typ', record_type, product_type)
        return False

    category_maps = body.get("CategoryMapCollection") or []
    if not isinstance(category_maps, list):
        print(f"ERROR - pominięto produkt {body.get('ProductNumber')} — CategoryMapCollection nie jest listą")
        return False

    return True
# --------------------------------------------------------------------------------------------------------------

def get_eans_to_fetch_single(category_type, categories_from_db, record):
    product_type = category_type.replace("_", " ")
    if not check_record(record, product_type):
        return None

    body = record.get("body") or {}
    category_maps = body.get("CategoryMapCollection", [])
    category_ids = []

    for mapping in category_maps:
        if not isinstance(mapping, dict):
            continue
        if mapping.get("SalesChannelId") != 1:  # tylko ISERVICE
            continue
        for cat in mapping.get("CategoryCollection", []):
            if not isinstance(cat, dict):
                continue
            category = get_category_by_id(cat.get("CategoryId"))
            categories_from_db[cat.get("CategoryId")] = category
            category_ids.append((category.get('categoryname_level3') if category else None) or cat.get("CategoryId"))

    action = body.get("ProductNumber", "")
    gtin_12 = ""
    gtin_13 = ""
    barcodes = body.get("BarcodeCollection", [])
    for b in barcodes:
        if b.get("BarCodeType") == "GTIN-13":
            gtin_13 = b.get("BarCode")
        if b.get("BarCodeType") == "GTIN-12":
            gtin_12 = b.get("BarCode")
   
    if not (action or gtin_12 or gtin_13):
        return None
    
    record.update({
        "action": action,
        "gtin_12": gtin_12,
        "gtin_13": gtin_13,
        "category_ids": category_ids
    })    

    return {(action, gtin_12, gtin_13): record}
# --------------------------------------------------------------------------------------------------------------

def get_eans_to_fetch(category_type, categories_from_db):
    start_index = 0
    count = int(os.environ.get('EAN_TEST_COUNT', 10000))
    end_index = start_index + count
    data_to_fetch = {}

    pim_list = load_pim_list(category_type)

    for idx, record in enumerate(pim_list[start_index:end_index], start=start_index):
        if idx % 10 == 0:
            print(f"--- Pobieranie z pliku {idx + 1}/{len(pim_list)} [max {count}] ---")
        
        data = get_eans_to_fetch_single(category_type, categories_from_db, record)
        if data:
            data_to_fetch.update(data)

    return data_to_fetch
# --------------------------------------------------------------------------------------------------------------


async def fetch_eans(eans_to_fetch):
    batch_size = 10
    products = {}

    connector = aiohttp.TCPConnector(limit=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        items = list(eans_to_fetch.items())
        total = len(items)

        # dzielimy na paczki po batch_size
        for start in range(0, total, batch_size):
            batch_items = items[start:start + batch_size]

            tasks = [
                process_single_ean(session, start + idx + 1, total, k, v)
                for idx, (k, v) in enumerate(batch_items)
            ]
            print(f"--- Pobieranie z pim {start}/{total} ---")

            batch_results = await asyncio.gather(*tasks)

            for idx, result in enumerate(batch_results):
                k, v = batch_items[idx]  # dane wejściowe
                product_key = next((x for x in k if x), None)
                if not product_key:
                    print("Brak klucza produktu w k:", k)
                    continue
                if result is None:
                    print("Brak danych dla:", product_key, k)
                    continue                

                panel = result.get("panel", {})
                if not panel:
                    print("Brak panel_data dla:", product_key, k)
                    continue
                specification = panel.get("specification", [])
                if not specification:
                    print("Brak specification w panelu dla:", product_key, k)
                    continue

                product_data = {}  # słownik specyfikacji
                for section in specification:
                    section_name = section.get("section_name", {}).get("PL")
                    if not section_name:
                        continue
                    product_data[section_name] = {}
                    for attr in section.get("attributes", []):
                        attribute_name = attr.get("attribute_name", {}).get("PL")
                        if not attribute_name:
                            continue
                        attribute_values = [
                            val.get("attribute_value_name", {}).get("PL") 
                            for val in attr.get("values", [])
                            if val.get("attribute_value_name") is not None
                        ]
                        product_data[section_name][attribute_name] = attribute_values

                # dodajemy dane wejściowe do słownika produktu
                products[product_key] = {
                    "category_ids": v.get("category_ids", []), 
                    "specification": product_data
                }
    print("Pobrano", len(products))
    return products
# --------------------------------------------------------------------------------------------------------------

def merge_attributes_with_translation(section_name, data, ai_map, categories_in_params):
    merged = {}
    translation = {}  # <-- lista tłumaczeń

    # mapowanie: jeśli nie ma w ai_map → zostaje jak jest
    target = {
        param: ai_map.get(param, "ZOSTAW")
        for param in data.keys()
    }

    # ustal rzeczywistą grupę docelową
    for param, decision in target.items():
        if decision == "ZOSTAW":
            target[param] = param
        else:
            target[param] = decision
            translation[param] = {"section": section_name, "param": decision}

    # utwórz puste listy NA PODSTAWIE realnych danych źródłowych
    for group in set(target.values()):
        merged[group] = []

    # scal wartości
    for param, values in data.items():
        group = target[param]
        for v in values:
            if v not in merged[group]:
                merged[group].append(v)

    # scal kategorie in params
    if categories_in_params:
        for section, params in list(categories_in_params.items()):
            for param, cats in list(params.items()):
                if param not in target:
                    continue

                target_param = target[param]

                # jeśli parametr zostaje → nic nie robimy
                if target_param == param:
                    continue

                # upewnij się, że struktura docelowa istnieje
                categories_in_params.setdefault(section, {})
                categories_in_params[section].setdefault(target_param, [])

                # merge kategorii (bez nadpisywania)
                for c in cats:
                    if c not in categories_in_params[section][target_param]:
                        categories_in_params[section][target_param].append(c)

                # usuń źródłowy parametr
                categories_in_params[section].pop(param, None)

    return merged, translation
# --------------------------------------------------------------------------------------------------------------

def merge_products(products, merged_products):
    for ean, product in products.items():
        # kategorie top-level
        for c in product.get("category_ids", []):
            if c not in merged_products["categories"]:
                merged_products["categories"].append(c)

        # sekcje
        spec = product.get("specification", {})
        for section_name, section_data in spec.items():
            # jeśli sekcja jeszcze nie istnieje → utwórz
            if section_name not in merged_products["specification"]:
                merged_products["specification"][section_name] = {}
            if section_name not in merged_products["categories_in_params"]:
                merged_products["categories_in_params"][section_name] = {}
            if section_name not in merged_products["product_params_cnt"]:
                merged_products["product_params_cnt"][section_name] = {}

            # iteracja po polach w sekcji
            for field_name, values in section_data.items():
                # jeśli pole nie istnieje → utwórz
                if field_name not in merged_products["specification"][section_name]:
                    merged_products["specification"][section_name][field_name] = []
                if field_name not in merged_products["categories_in_params"][section_name]:
                    merged_products["categories_in_params"][section_name][field_name] = []
                if field_name not in merged_products["product_params_cnt"][section_name]:
                    merged_products["product_params_cnt"][section_name][field_name] = 0

                # dodawanie unikalnych wartości do specification
                for v in values:
                    if v not in merged_products["specification"][section_name][field_name]:
                        merged_products["specification"][section_name][field_name].append(v)

                # dodawanie unikalnych kategorii do categories_in_params
                for c in product.get("category_ids", []):
                    if c not in merged_products["categories_in_params"][section_name][field_name]:
                        merged_products["categories_in_params"][section_name][field_name].append(c)

                merged_products["product_params_cnt"][section_name][field_name] = merged_products["product_params_cnt"][section_name][field_name] + 1

    return merged_products

# --------------------------------------------------------------------------------------------------------------

def apply_to_remove(all_params, to_remove, categories_in_params=None, translations=None):
    categories_in_params = categories_in_params or {}
    translations = translations or {}
    if "Oczyszczone" not in all_params:
        all_params["Oczyszczone"] = {}
    if "Oczyszczone" not in translations:
        translations["Oczyszczone"] = {}
    if "Oczyszczone" not in categories_in_params:
        categories_in_params["Oczyszczone"] = {}

    for section, params in to_remove.items():
        # ⬅️ jeśli sekcji nie ma w all_params → pomijamy
        if section not in all_params:
            continue

        section_data = all_params.get(section)
        if not isinstance(section_data, dict):
            continue  # sekcja istnieje, ale nie jest słownikiem → pomijamy

        for param, reason in params.items():  # 'reason' to wartość z to_remove
            # ⬅️ jeśli parametr nie istnieje w sekcji → pomijamy
            if param not in section_data:
                continue

            # sprawdzamy, czy wartość zaczyna się od "USUN"
            if isinstance(reason, str) and reason.strip().startswith("USUN"):
                translations[section][param] = {"section": "Oczyszczone", "param":param}
                if param not in all_params["Oczyszczone"]:
                    all_params["Oczyszczone"][param] = section_data.get(param)
                else:
                    source_values = section_data.get(param, [])
                    target_values = all_params["Oczyszczone"].get(param, [])
                    merged = list(dict.fromkeys(target_values + source_values))
                    all_params["Oczyszczone"][param] = merged
                section_data.pop(param, None)

                # ⬅️ dodatkowo usuń z categories_in_params
                if categories_in_params and section in categories_in_params:
                    removed_values = categories_in_params[section].pop(param, None)
                    if removed_values:
                        if param not in categories_in_params["Oczyszczone"]:
                            categories_in_params["Oczyszczone"][param] = removed_values
                        else:
                            existing_values = categories_in_params["Oczyszczone"][param]
                            categories_in_params["Oczyszczone"][param] = list(dict.fromkeys(existing_values + removed_values))

            # sprawdzamy, czy wartość zaczyna się od "PRZESUN DO"
            if isinstance(reason, str) and reason.strip().startswith("PRZESUN DO"):
                match = re.search(r'PRZESUN DO\s*<([^>]+)>', reason)
                if match:
                    target_section = match.group(1)
                    # ⬅️ jeśli sekcji docelowej nie ma → pomijamy
                    if target_section not in all_params:
                        continue

                    target_data = all_params.get(target_section)
                    if not isinstance(target_data, dict):
                        continue  # sekcja docelowa nie jest słownikiem → pomijamy

                    translations[section][param] = {"section": target_section, "param":param}
                    if param not in target_data:
                        target_data[param] = section_data.get(param)
                    else:
                        source_values = section_data.get(param, [])
                        target_values = target_data.get(param, [])
                        merged = list(dict.fromkeys(target_values + source_values))
                        target_data[param] = merged
                    section_data.pop(param, None)

                    # ⬅️ dodatkowo przenieś categories_in_params
                    if categories_in_params:
                        if section in categories_in_params and param in categories_in_params[section]:
                            source_categories = categories_in_params[section].pop(param)
                            if target_section not in categories_in_params:
                                categories_in_params[target_section] = {}

                            if param not in categories_in_params[target_section]:
                                categories_in_params[target_section][param] = source_categories
                            else:
                                target_categories = categories_in_params[target_section][param]
                                merged_categories = list(dict.fromkeys(target_categories + source_categories))
                                categories_in_params[target_section][param] = merged_categories

    return all_params



def save_to_output_dir_factory(output_dir):
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path
    return save_to_output_dir
# --------------------------------------------------------------------------------------------------------------

def rename_attributes_in_products(products, translates):
    renamed_products = {}

    for ean, product_data in products.items():
        specification = product_data.get("specification", {})
        new_spec = {}

        for section_name, section_attrs in specification.items():
            attr_map = translates.get(section_name, {})

            for attr_name, values in section_attrs.items():
                translate = attr_map.get(attr_name)

                # domyślne wartości (brak tłumaczenia)
                target_section = section_name
                target_param = attr_name

                # jeśli istnieje mapowanie
                if isinstance(translate, dict):
                    target_section = translate.get("section", section_name)
                    target_param = translate.get("param", attr_name)

                # utwórz sekcję docelową jeśli nie istnieje
                if target_section not in new_spec:
                    new_spec[target_section] = {}

                # jeśli parametr już istnieje → łącz wartości
                if target_param in new_spec[target_section]:
                    existing_values = new_spec[target_section][target_param]
                    for v in values:
                        if v not in existing_values:
                            existing_values.append(v)
                else:
                    new_spec[target_section][target_param] = values.copy()

        renamed_products[ean] = {
            **product_data,
            "specification": new_spec
        }

    return renamed_products

def rename_attributes_in_products_OLD(products, translates):
    renamed_products = {}

    for ean, product_data in products.items():
        specification = product_data.get("specification", {})
        new_spec = {}

        for section_name, section_attrs in specification.items():
            new_section = {}
            attr_map = translates.get(section_name, {})

            for attr_name, values in section_attrs.items():
                new_name = attr_map.get(attr_name, attr_name)
                if new_name == "":
                    new_name = attr_name

                # jeśli klucz już istnieje → połącz wartości, unikając duplikatów
                if new_name in new_section:
                    existing_values = new_section[new_name]
                    for v in values:
                        if v not in existing_values:
                            existing_values.append(v)
                    new_section[new_name] = existing_values
                else:
                    new_section[new_name] = values.copy()

            new_spec[section_name] = new_section

        renamed_products[ean] = {
            **product_data,
            "specification": new_spec
        }

    return renamed_products

def remove_attributes_from_products(products, to_remove, translates):
    changed_products = {}

    for ean, product_data in products.items():
        specification = product_data.get("specification", {})
        categories_in_params = product_data.get("categories_in_params", {})
        specification = apply_to_remove(specification, to_remove, categories_in_params, translates)

        changed_products[ean] = {
            **product_data,
            "specification": specification,
            "categories_in_params": categories_in_params
        }

    return changed_products

async def etl2_create_spec_aka_single(request):
    output_dir = create_output_directory()
    save_to_output_dir = save_to_output_dir_factory(output_dir)

    # wczytanie danych z szyny
    record = await request.json()  # produkt z szyny

    # rozpoznanie typu kategorii
    body = record.get("body", {})
    categories_type = body.get("ProductType") or ''
    if not categories_type:
        return JSONResponse({"result": False, "mess": "Brak ProductType w body"})

    categories_from_db = {}
    eans_to_fetch = get_eans_to_fetch_single(categories_type, categories_from_db, record)
    products = await fetch_eans(eans_to_fetch)
    #products["5900951014352"]["specification"]["Cechy"]["aka"] = ["du","da"]
    save_to_output_dir(products, f'a0_products')    
    # pobranie formatek
    forms = get_forms(categories_type)
    save_to_output_dir(forms, f'a1_forms')    
    # Jeśli formatka nie istnieje → zatrzymujemy proces
    if forms is None:
        return JSONResponse({"result": False, "mess": f"Brak formatki w tabeli forms dla kategorii {categories_type}"})    
    # obsługa translates
    products = rename_attributes_in_products(products, forms.get("translates"))
    save_to_output_dir(products, f'a2_products')    
    products = remove_attributes_from_products(products, forms.get('to_remove'), forms.get("translates"))
    save_to_output_dir(products, f'a2_products_removed')    

    merged_products = {}
    merged_products["categories"] = (forms.get("form") or [{}])[0].get("secondary_key", [])
    merged_products["categories_in_params"] = forms.get('categories')
    merged_products["specification"] = forms.get('llm_form')
    merged_products["product_params_cnt"] = forms.get('product_params_cnt')
    merged_before = copy.deepcopy(merged_products)

    merged_products = merge_products(products, merged_products)
    if merged_before == merged_products: # nic sie nie zmienilo
        print("nic sie nie zmienilo")
        return JSONResponse({"result": True})
    diff = dict_diff(merged_before, merged_products)
    save_to_output_dir(merged_before, f'a3_before')
    save_to_output_dir(merged_products, f'a4_after')
    save_to_output_dir(diff, f'a5_diff')
    

    # nazwa kategorii dla llma
    product_type = categories_type.replace("_", " ")
    # wczytaj mapping sekcji
    with open("data/section_mapping.json", "r", encoding="utf-8") as f:
        section_mapping = json.load(f)
    await process_merged_products(product_type, merged_products, categories_from_db, section_mapping, save_to_output_dir)

    return JSONResponse({
        "result": True
    })
# --------------------------------------------------------------------------------------------------------------


async def etl2_create_spec_aka(request):
    # funkcja pomocnicza do zapisywania plików w katalogu wyjściowym
    output_dir = create_output_directory()
    save_to_output_dir = save_to_output_dir_factory(output_dir)

    # ręczne mapowanie sekcji 
    with open("data/section_mapping.json", "r", encoding="utf-8") as f:
        section_mapping = json.load(f)

    # wczytanie danych z plików 
    data = await request.json()  # wejście np. lista lub jakieś parametry
    category_types = load_category_types(data["type"]) # jakie pliki bierzemy ("ALL" czy wybrany typ np. "Karma")

    for category_type in category_types:
        categories_from_db = {} # kategorie występujące dla typu (w formatce)
        eans_to_fetch = get_eans_to_fetch(category_type, categories_from_db)
        products = await fetch_eans(eans_to_fetch)
        save_to_output_dir(products, f'tmp_products')

        # nazwa kategorii dla llma
        product_type = category_type.replace("_", " ")

        # dane z wszystkich formatek w 1 miejscu
        merged_products = {}
        merged_products["categories"] = [] #wszystkie kategorie dla tego typu produktow
        merged_products["categories_in_params"] = {} #kategorie w atrybutach
        merged_products["specification"] = {}    
        merged_products["product_params_cnt"] = {}
        merged_products = merge_products(products, merged_products)
        save_to_output_dir(merged_products, f'x1_merged_products')
        save_to_output_dir(merged_products["categories"], f'x2_categories')
        save_to_output_dir(merged_products["categories_in_params"], f'x3_categories_in_params')
        save_to_output_dir(merged_products["product_params_cnt"], f'x4_product_params_cnt')

        #akaduda
        await process_merged_products(product_type, merged_products, categories_from_db, section_mapping, save_to_output_dir)

    return JSONResponse({
        "result": True
    })

async def process_merged_products(product_type, merged_products, categories_from_db, section_mapping, save_to_output_dir):
    all_params = {} # pierwsza wersja formatki od AI (łączenie atrybutów w sekcjach)
    translations = {} # tablica łączenia atrybutów w sekcjach
    #translations['sections'] = section_mapping # ręcznie ustawione przeniesienia / usuwanie sekcji

    # pierwsza wersja formatki od AI (łączenie atrybutów w sekcjach)
    i = 0
    for section_name, section_data in merged_products["specification"].items():
        i = i + 1
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Tworzę formatkę dla {product_type} {section_name} {len(json.dumps(section_data, ensure_ascii=False))} (AI)")
        ai_analysis = ai_analyze_and_create_form_new(product_type, section_name, section_data, merged_products["product_params_cnt"][section_name], f'section_{i}', save_to_output_dir)
        if ai_analysis:
            all_params[section_name], translations[section_name] = merge_attributes_with_translation(section_name, section_data, ai_analysis, merged_products["categories_in_params"])
            save_to_output_dir(section_data, f'ai_item_{i}_we')
            save_to_output_dir(translations[section_name], f'ai_item_{i}_wy')
        else:
            print("nie mam odpowiedzi")
            all_params[section_name] = section_data
            translations[section_name] = {}

    save_to_output_dir(all_params, f'y1_all_params')
    save_to_output_dir(translations, f'y2_translations')

    # druga werdja formatki od AI (usuwanie zduplikowanych atrybutów pomiędzy sekcjami)
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Usuwam duplikaty {len(json.dumps(all_params, ensure_ascii=False))} (AI)")
    to_remove = ai_remove_duplicates(product_type, all_params, f'without_duplicates', save_to_output_dir)
    save_to_output_dir(to_remove, f'y3_to_remove_final_ai')
    all_params = apply_to_remove(all_params, to_remove, merged_products["categories_in_params"], translations)
    save_to_output_dir(all_params, f'y4_all_params_without_duplicates')
    save_to_output_dir(translations, f'y5_translations')

    #zasugeruj nazwy zmian sekcji - NIE UZYWAMY
    # print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Zmiany nazw sekcji {len(json.dumps(all_params, ensure_ascii=False))} (AI)")
    # sugest_section_names = ai_sugest_section_names(product_type, all_params, f'zz_new_section_names_final', save_to_output_dir)
    # save_to_output_dir(sugest_section_names, f'y5_new_section_names_final')
    #exit()
    # ustal kolejność
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Ustalam kolejność {len(json.dumps(all_params, ensure_ascii=False))} (AI)")
    ordered = ai_set_order(product_type, all_params, f'ordered', save_to_output_dir)
    if not ordered:
        ordered = all_params
    save_to_output_dir(ordered, f'y6_ordered')

    # stwórz dane podstawowe i oczyść z danych przykładowych
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Tworzę dane podstawowe {len(json.dumps(ordered, ensure_ascii=False))} (AI)")
    main_data = ai_add_main_data(product_type, ordered, f'main_data', save_to_output_dir)
    main_data = {
        "Dane podstawowe": main_data
    }
    save_to_output_dir(main_data, f'y7_main_data')

    main_data_with_examples = {}
    for section, attrs in main_data.items():
        main_data_with_examples[section] = {}
        for attr, group in attrs.items():
            if group in ordered and attr in ordered[group]:
                main_data_with_examples[section][attr] = ordered[group][attr]
            else:
                main_data_with_examples[section][attr] = []
    save_to_output_dir(main_data_with_examples, f'y8_main_data_with_examples')    
    ordered_with_main = {**main_data_with_examples, **ordered}
    save_to_output_dir(ordered_with_main, f'y9_ordered_with_main')
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Tworzę finalną formatkę")
    without_examples = {category: list(params.keys()) for category, params in ordered.items()}
    final_specs = {**main_data, **without_examples}
    #main_data_wihout_examples = {category: list(params.keys()) for category, params in main_data.items()}
    #final_specs = {**main_data_wihout_examples, **without_examples}
    save_to_output_dir(final_specs, f'z1_specs_final')
    
    #tworzenie formatki
    form = build_form({}, ordered_with_main, merged_products["categories"], include_values=False)
    form_with_values = build_form({}, ordered_with_main, merged_products["categories"], include_values=True)
    save_to_output_dir(form, f'z2_form')
    save_to_output_dir(form_with_values, f'z3_form_with_values')
    form_save(product_type, ordered, form, form_with_values, translations, merged_products["categories_in_params"], to_remove, merged_products["product_params_cnt"], main_data)

    # zapisz do tabeli category_to_type
    # category_to_type(product_type, product_type) - dodanie typu do listy kategorii
    for cat_id, category in categories_from_db.items():
        if (isinstance(category, dict)):
            level3 = (category.get("categoryname_level3") or "").replace("-", "_")
            level2 = (category.get("categoryname_level2") or "").replace("-", "_")
            # category_to_type(product_type, level3) # dodanie liscia do listy kategorii
            category_to_type(product_type, f"{level2} / {level3}") # dodanie sciezki do listy kategorii
            add_nodes_data = {"name":f"{level2} / {level3}", "code":f"{level2} / {level3}", "specification":form}
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
    add_truncated_sections(product_type, save_to_output_dir)
    await map_values_logic({"category": product_type})


def dict_diff(d1, d2, path="root"):
    """
    Porównuje dwa zagnieżdżone słowniki/listy i zwraca listę różnic.
    """
    diffs = []

    if isinstance(d1, dict) and isinstance(d2, dict):
        all_keys = set(d1.keys()) | set(d2.keys())
        for key in all_keys:
            new_path = f"{path}['{key}']"
            if key not in d1:
                diffs.append(f"{new_path} - klucz dodany: {d2[key]}")
            elif key not in d2:
                diffs.append(f"{new_path} - klucz usunięty")
            else:
                diffs.extend(dict_diff(d1[key], d2[key], new_path))

    elif isinstance(d1, list) and isinstance(d2, list):
        # porównanie list element po elemencie
        len1, len2 = len(d1), len(d2)
        min_len = min(len1, len2)
        for i in range(min_len):
            new_path = f"{path}[{i}]"
            diffs.extend(dict_diff(d1[i], d2[i], new_path))
        if len1 < len2:
            for i in range(len1, len2):
                diffs.append(f"{path}[{i}] - element dodany: {d2[i]}")
        elif len1 > len2:
            for i in range(len2, len1):
                diffs.append(f"{path}[{i}] - element usunięty: {d1[i]}")

    else:
        # porównanie wartości końcowych
        if d1 != d2:
            diffs.append(f"{path} - zmieniono z {d1} na {d2}")

    return diffs
