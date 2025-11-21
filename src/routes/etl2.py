# src/routes/etl2.py
from starlette.responses import JSONResponse
import aiohttp
import asyncio
import json
import os
import re
from src.services.ean_service import send_message, is_ean_valid, generate_ean_variants
from src.services.ai_service import ai_analyze_and_create_form, ai_add_main_data, ai_remove_duplicates, ai_set_order, ai_sugest_section_names, ai_remove_excess_sections
from src.services.file_service import save_json_file
from src.services.form_service import build_form
from src.services.db_service import form_save, get_category_by_id, category_to_type, get_forms, get_categories_in_type, add_excludes_to_search

import datetime
import os

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

def add_truncated_sections(categories_type, save_to_output_dir):
    forms = get_forms(categories_type)
    categories = get_categories_in_type(categories_type)

    for category in categories:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Optymalizacja dla {category['category']} (AI)")
            filename = re.sub(r'[<>:"/\\|?*\n\r\t]', '_', category['category'])
            excludes = ai_remove_excess_sections(category['category'], forms['llm_form'], f"optymalization_{filename}", save_to_output_dir)
            add_excludes_to_search(category['category'], excludes)
            save_to_output_dir(excludes, f"excludes_{filename}")

async def process_single_ean(session, idx, total, k, v):
    if not is_ean_valid(v['gtin']):
        print("nieprawidłowy EAN", v['gtin'])
        return None

    single_spec = None
    ean_variants = generate_ean_variants(v['gtin'])

    # Równoległe sprawdzenie wszystkich wariantów EAN
    tasks = [send_message(session, "get_ean", variant) for variant in ean_variants]
    results = await asyncio.gather(*tasks)

    for result in results:
        if result:
            single_spec = result
            break

    if not single_spec and v.get('part_number'):
        single_spec = await send_message(session, "get_pn", v['partNumber'])

    print(f"{idx}/{total} EAN: {v['gtin']} | progress: {100 * idx / total:.1f}%")

    return {'panel': single_spec['panel_data'], 'specification': single_spec['specification']} if single_spec else None

async def etl2_create_spec_aka(request):
    # funkcja pomocnicza do zapisywania plików w katalogu wyjściowym
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, f'{filename}')
        save_json_file(data, file_path)
        return file_path
    
    # utworzenie katalogu wyjściowego
    output_dir = create_output_directory()

    # ręczne mapowanie sekcji 
    with open("data/section_mapping.json", "r", encoding="utf-8") as f:
        section_mapping = json.load(f)

    # wczytanie danych z plików (pobranych z szyny)
    data = await request.json()  # wejście np. lista lub jakieś parametry
    type = data["type"]
    base_path = f"database/pim_by_type/{type}"
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

    # nazwa kategorii dla llma
    product_type = type.replace("_", " ")
    category_desc = product_type

    # przetwarzanie pobranych plików
    start_index = 0
    count = 20
    end_index = start_index + count
    data = {}
    tt = 0
    limit = 10000
    categories_from_db = {}
    #limit = 1
#    return JSONResponse({        "result": True    })       
    for idx, record in enumerate(pim_list):
#    for idx, record in enumerate(pim_list[start_index:end_index], start=start_index):
        #print(f"\n--- Przetwarzanie obiektu {idx + 1}/{len(pim_list)} ---")

        # wstępna weryfikacja danych wejściowych
#        if not pim_data['body'].get('BarcodeCollection'):
            #print(f"Brak EAN dla ProductNumber: {pim_data['body'].get('ProductNumber')}")

        if not isinstance(record, dict):
            print("ERROR - pominięto rekord — nie jest słownikiem:", record)
            continue

        body = record.get("body") or {}
        if not isinstance(body, dict):
            print("ERROR - pominięto rekord — body to None lub nie dict")
            continue

        #print('---------------------------------------------')
        #print(body.get("ProductNumber"))

        record_type = body.get("ProductType") or ''
        if record_type != product_type:
            print('ERROR - pominięto rekord — błędny typ', record_type, product_type)
            continue

        category_maps = body.get("CategoryMapCollection") or []
        if not isinstance(category_maps, list):
            print(f"ERROR - pominięto produkt {body.get('ProductNumber')} — CategoryMapCollection nie jest listą")
            #print(json.dumps(record, indent=2, ensure_ascii=False))
            continue


        category_ids = []
        for mapping in category_maps:
            if not isinstance(mapping, dict):
                continue

            if mapping.get("SalesChannelId") == 1: #ISERWICE
                for cat in (mapping.get("CategoryCollection") or []):
                    if not isinstance(cat, dict):
                        continue

                    category = get_category_by_id(cat.get("CategoryId"))
                    categories_from_db[cat.get("CategoryId")] = category
                    category_ids.append(
                        (category.get('categoryname_level3') if category else None)
                        or cat.get("CategoryId")
                    )

        barcodes = body.get("BarcodeCollection", [])
        gtin = None
        for b in barcodes:
            if b.get("BarCodeType") == "GTIN-13":
                gtin = b.get("BarCode")
                break

        if gtin:
            record["gtin"] = gtin
            record["category_ids"] = category_ids
            data[gtin] = record
            tt = tt+1
        else:
            print(f"ERROR - brak GTIN dla produktu {body.get('ProductNumber')}")
            #print(json.dumps(record, indent=2, ensure_ascii=False))

        if tt > limit:
            break
    connector = aiohttp.TCPConnector(limit=30)

    async with aiohttp.ClientSession(connector=connector) as session:
        all_params = {}
        translates = {}
        translates['sections'] = section_mapping
        params_for_categories = {}
        products = {}
        total = len(data)
        ai_cnt = 0
        #total = 2
        trans_lang = {}
        categories = []


        for i, (k, v) in enumerate(data.items(), start=1):
            if i > total:
                break
            result = await process_single_ean(session, i, total, i, v)
            #print("ean", result)
            if not result:
                continue
            
            #save_to_output_dir(result, f"ean_{v['gtin']}")
            params = result['panel']["specification_values"]["PL"]
            for section in result["specification"]:
                trans_lang[section["section_name"]["PL"]] = section["section_name"]
                for attr in section["attributes"]:
                    trans_lang[attr["PL"]] = attr
            #print("panel", params)
            products[v['gtin']] = params
            #if v['groupId'] not in categories:
            #    categories.append(v['groupId'])
            for c in v['category_ids']:
                if c not in categories:
                    categories.append(c)

            array_params = {
                category: {k: [v] for k, v in specs.items()}
                for category, specs in params.items()
            }
            if not all_params:
                all_params = array_params

            potential_new = {}   # wartości/kategorie, które mogłyby być dodane, ale ich nie dodano

            for category, specs in array_params.items():
                if category not in params_for_categories:
                    params_for_categories[category] = {}

                if category in all_params:  # tylko istniejące kategorie
                    for key, value in specs.items():
                        key_to_use = translates.get(category, {}).get(key, key)

                        if key_to_use in all_params[category]:  # tylko istniejące klucze
                            # nowe wartości, których jeszcze nie ma w all_params
                            new_vals = [v for v in value if v not in all_params[category][key_to_use ]]
                            if new_vals:
                                all_params[category][key_to_use].extend(new_vals)
                            if key_to_use not in params_for_categories[category]:
                                params_for_categories[category][key_to_use] = []
                            #if v['groupId'] not in params_for_categories[category][key_to_use]:
                            #    params_for_categories[category][key_to_use].append(v['groupId'])
                            for c in v['category_ids']:
                                if c not in params_for_categories[category][key_to_use]:
                                    params_for_categories[category][key_to_use].append(c)

                        else:
                            # nowy klucz w istniejącej kategorii (nie dodajemy)
                            if category not in potential_new:
                                potential_new[category] = {}
                            potential_new[category][key_to_use] = value
                else:
                    # nowa kategoria (nie analizujemy, tylko dodajemy do formatki)
                    all_params[category] = specs

            if potential_new:
                #save_to_output_dir(potential_new, f'potential_new_{i}')
                #save_to_output_dir(all_params, f'all_params_aa_before_{i}')
                #save_to_output_dir(translates, f'translates_aa_before_{i}')
                for category, params in potential_new.items():
                    ai_cnt += 1
                    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Analiza AI {ai_cnt}")
                    #def ai_analyze_and_create_form(category, section, current_structure, data, filename_prefix, save_function, final=False, max_attempts=2):
                    ai_analysis = ai_analyze_and_create_form(category_desc, category, all_params[category], params, f'item_{i}', save_to_output_dir)
                    #print(ai_analysis)
                    if ai_analysis:
                        for par, val in ai_analysis.items():
                            if val == 'NOWA':
                                all_params[category][par] = potential_new[category][par]
                                if par not in params_for_categories[category]:
                                    params_for_categories[category][par] = []
                                #if v['groupId'] not in params_for_categories[category][par]:
                                #    params_for_categories[category][par].append(v['groupId'])
                                for c in v['category_ids']:
                                    if c not in params_for_categories[category][par]:
                                        params_for_categories[category][par].append(c)


                            else:
                                #val - to co juz istnieje
                                #par - z nowego produktu, ma byc mapowane na val
                                print("dodaje translacje:", par, "- to to samo co:" ,val)
                                #translates[category][par] = val
                                translates.setdefault(category, {})[par] = val
                                par_old = par
                                par = val
                                #all_params[category][par] = list(set(all_params[category][par] + potential_new[category][par]))
                                if par not in all_params[category]:
                                    # jeśli to nowy klucz, dodaj go razem z wartościami
                                    all_params[category][par] = potential_new[category][par_old]
                                else:
                                    # jeśli już istnieje, dołącz nowe wartości (bez duplikatów)
                                    all_params[category][par] = list(
                                        set(all_params[category][par] + potential_new[category][par_old])
                                    )
                                #all_params[category][par] = potential_new[category][par]

                                if par not in params_for_categories[category]:
                                    params_for_categories[category][par] = []

                                #if v['groupId'] not in params_for_categories[category][par]:
                                #    params_for_categories[category][par].append(v['groupId'])
                                for c in v['category_ids']:
                                    if c not in params_for_categories[category][par]:
                                        params_for_categories[category][par].append(c)
                                if par_old in params_for_categories[category]:
                                    for gid in params_for_categories[category][par_old]:
                                        if gid not in params_for_categories[category][par]:
                                            params_for_categories[category][par].append(gid)
                                    del params_for_categories[category][par_old]

                #save_to_output_dir(all_params, f'all_params_after_{i}')
                #save_to_output_dir(translates, f'translates_after_{i}')
                
                
        print(f"Analiz AI total: {ai_cnt}")

        save_to_output_dir(all_params, f'zz_all_params')
        save_to_output_dir(products, f'zz_products')
        save_to_output_dir(translates, f'zz_translates_final')
        save_to_output_dir(params_for_categories, f'zz_categories_final')

        # mapowanie
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Mapuję")
        print(section_mapping)
        for section, target in list(section_mapping.items()):
            if section in all_params:
                if target == "":
                    # usuń całą sekcję
                    print("usuwam sekcje", section)
                    del all_params[section]
                else:
                    # jeśli sekcji docelowej nie ma – utwórz pustą
                    if target not in all_params:
                        all_params[target] = {}
                    # scal parametry
                    for param, value in all_params[section].items():
                        if param in all_params[target]:
                            existing = all_params[target][param]
                            # jeśli oba są listami → połącz unikalnie
                            if isinstance(existing, list) and isinstance(value, list):
                                print("łączę 1", section)
                                all_params[target][param] = list(set(existing) | set(value))
                            # jeśli nie są listami → nadpisz
                            else:
                                print("łączę 2", section)
                                all_params[target][param] = value
                        else:
                            print("łączę 3", section)
                            all_params[target][param] = value
                    # usuń starą sekcję
                    print("usuwam sekcje", section)
                    del all_params[section]
        save_to_output_dir(all_params, f'zz_all_params_after_mapping')

        # usuń duplikaty
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Usuwam duplikaty (AI)")
        to_remove = ai_remove_duplicates(category_desc, all_params, f'without_duplicates', save_to_output_dir)
        save_to_output_dir(to_remove, f'zz_to_remove_final')
        for section, params in to_remove.items():
            if section in all_params:
                for param, reason in params.items():  # 'reason' to wartość z to_remove
                    # sprawdzamy, czy w to_remove wartość zaczyna się od "USUN"
                    if isinstance(reason, str) and reason.strip().startswith("USUN"):
                        if param in all_params[section]:
                            del all_params[section][param]
        save_to_output_dir(all_params, f'zz_all_params_without_duplicates')

        #usun sekcje - dla kazdej kategorii z osobna
        #for category in categories:
        #    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Optymalizacja dla {category} (AI)")
        #    truncated = ai_remove_excess_sections(category, all_params, f'optymalization_{category}', save_to_output_dir)
        #    save_to_output_dir(truncated, f'truncated_{category}')

        #zasugeruj nazwy zmian sekcji
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Zmiany nazw sekcji (AI)")
        sugest_section_names = ai_sugest_section_names(category_desc, all_params, f'zz_new_section_names_final', save_to_output_dir)
        save_to_output_dir(sugest_section_names, f'zz_new_section_names_final')

        # ustal kolejność
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Ustalam kolejność (AI)")
        ordered = ai_set_order(category_desc, all_params, f'ordered', save_to_output_dir)
        if not ordered:
            ordered = all_params
        save_to_output_dir(ordered, f'zz_all_params_with_order')

        # stwórz dane podstawowe i oczyść z danych przykładowych
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Tworzę dane podstawowe (AI)")
        main_data = ai_add_main_data(category_desc, ordered, f'main_data', save_to_output_dir)
        main_data = {
            "Dane podstawowe": main_data
        }
        save_to_output_dir(main_data, f'zz_all_params_with_main_data')

        main_data_with_examples = {}
        for section, attrs in main_data.items():
            main_data_with_examples[section] = {}
            for attr, group in attrs.items():
                if group in ordered and attr in ordered[group]:
                    main_data_with_examples[section][attr] = ordered[group][attr]
                else:
                    main_data_with_examples[section][attr] = []
        save_to_output_dir(main_data_with_examples, f'zz_main_data_with_examples')    
        ordered_with_main = {**main_data_with_examples, **ordered}
        save_to_output_dir(ordered_with_main, f'zz_ordered_with_main')
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} - Tworzę finalną formatkę")
        without_examples = {category: list(params.keys()) for category, params in ordered.items()}
        final_specs = {**main_data, **without_examples}
        #main_data_wihout_examples = {category: list(params.keys()) for category, params in main_data.items()}
        #final_specs = {**main_data_wihout_examples, **without_examples}
        save_to_output_dir(final_specs, f'zz_specs_final')
        
        #tworzenie formatki
        #form = build_form(trans_lang, ordered, categories, include_values=False)
        #form_with_values = build_form(trans_lang, ordered, categories, include_values=True)
        #form_save(categories, ordered, form, form_with_values, translates, params_for_categories)

        form = build_form(trans_lang, ordered_with_main, categories, include_values=False)
        form_with_values = build_form(trans_lang, ordered_with_main, categories, include_values=True)
        save_to_output_dir(form, f'zz_zz_form')
        save_to_output_dir(form_with_values, f'zz_zz_form_with_values')
        form_save(product_type, ordered, form, form_with_values, translates, params_for_categories)

        # zapisz do tabeli category_to_type
        category_to_type(product_type, product_type)
        for cat_id, category in categories_from_db.items():
            if (isinstance(category, dict)):
                level3 = (category.get("categoryname_level3") or "").replace("-", "_")
                level2 = (category.get("categoryname_level2") or "").replace("-", "_")
                category_to_type(product_type, level3)
                category_to_type(product_type, f"{level2} / {level3}")
            else:
                category_to_type(product_type, str(cat_id))

        add_truncated_sections(product_type, save_to_output_dir)

    return JSONResponse({
        "result": True
    })

