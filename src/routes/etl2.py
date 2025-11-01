# src/routes/etl2.py
from starlette.responses import JSONResponse
import aiohttp
import asyncio
import json
import os
from src.services.ean_service import read_eans, send_message, is_ean_valid, generate_ean_variants, read_eans_from_file
from src.services.specification_service import merge_specifications, combine_specifications_with_values, normalize_specification 
from src.services.ai_service import analyze_and_save, ai_analyze_and_create_form, ai_add_main_data, ai_remove_duplicates, ai_set_order, ai_sugest_section_names
from src.services.file_service import save_json_file
from src.services.form_service import build_form
from src.services.db_service import form_save, get_category_by_id

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


def clean_duplicate_mapping(duplicate_mapping):
    """
    Usuwa z listy duplikatów nazwy identyczne z kluczami kanonicznymi
    oraz rozwiązuje problem hierarchii duplikatów, zachowując puste klucze.

    Args:
        duplicate_mapping (dict): Mapa duplikatów do oczyszczenia

    Returns:
        dict: Oczyszczona mapa duplikatów
    """
    # Najpierw budujemy odwrotną mapę: duplikat -> nazwa kanoniczna
    reverse_mapping = {}
    for section, mappings in duplicate_mapping.items():
        for canonical_name, duplicates in mappings.items():
            for dup in duplicates:
                reverse_mapping.setdefault(section, {})[dup] = canonical_name

    # Przygotowujemy nową mapę
    cleaned_mapping = {}
    print(reverse_mapping)
    # Rozwiązujemy problem hierarchii duplikatów
    for section, mappings in duplicate_mapping.items():
        cleaned_mapping[section] = {}
        section_reverse = reverse_mapping.get(section, {})

        for canonical_name, duplicates in mappings.items():
            # Pomijamy wpisy, gdzie nazwa kanoniczna jest duplikatem
            if canonical_name in section_reverse:

                higher_canonical = section_reverse[canonical_name]


                # Przekazujemy "osierocone" duplikaty do wyższego poziomu
                for dup in duplicates:
                    if dup != canonical_name and dup != higher_canonical:

                        cleaned_mapping[section].setdefault(higher_canonical, []).append(dup)
                if duplicates:
                    cleaned_mapping[section].setdefault(higher_canonical, []).append(canonical_name)

                continue

            # Usuwamy z listy duplikatów sam klucz kanoniczny
            cleaned_duplicates = [dup for dup in duplicates if dup != canonical_name]

        # Dodajemy zawsze, nawet jeśli lista duplikatów jest pusta
            if canonical_name not in cleaned_mapping[section]:
                cleaned_mapping[section][canonical_name] = cleaned_duplicates
            # cleaned_mapping[section][canonical_name] = cleaned_duplicates

    # Usuwamy potencjalne duplikaty w listach duplikatów po przekierowaniu
    for section, mappings in cleaned_mapping.items():
        for canonical_name, duplicates in mappings.items():
            cleaned_mapping[section][canonical_name] = list(dict.fromkeys(duplicates))

    return cleaned_mapping

async def etl2_create_spec(request):
    # Utworzenie katalogu wyjściowego
    output_dir = create_output_directory()

    # Funkcja pomocnicza do zapisywania plików w katalogu wyjściowym
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    data_lcd = await read_eans_from_file('data/TVA-LCD.json')
    data_oled = await read_eans_from_file('data/TVA-OLE.json')
    
    data = {**{d['gtin']: d for d in data_lcd}, **{d['gtin']: d for d in data_oled}}
    connector = aiohttp.TCPConnector(limit=30)

    async with aiohttp.ClientSession(connector=connector) as session:
        all_specs = []
        all_examples = []
        merged_specification = []
        #total = len(data)
        total = 20
        batch_size = 10
        language = "PL"

        # Inicjalizacja globalnej mapy duplikatów
        global_duplicate_mapping = {}

        for batch_num, i in enumerate(range(0, total, batch_size)):
            print(f"Przetwarzanie batcha {batch_num + 1}")

            # 1. Wczytaj batch
            batch_items = list(data.items())[i:i + batch_size]
            tasks = [process_single_ean(session, idx + i, total, k, v) for idx, (k, v) in enumerate(batch_items)]
            batch_results = await asyncio.gather(*tasks)

            # 2. Filtrowanie i normalizacja batcha
            batch_specs = [spec for spec in batch_results if spec]
            batch_specifications = [
                normalize_specification(spec.get("specification", []), global_duplicate_mapping)
                for spec in batch_specs if spec
            ]

            # 3. Merge batcha
            batch_merged = []
            for specification in batch_specifications:
                batch_merged = merge_specifications(batch_merged, specification)

            # 4. Merge z wcześniejszym wynikiem
            merged_specification = merge_specifications(merged_specification, batch_merged)

            # 5. Dodaj examples
            batch_examples = [panel['panel']["specification_values"] for panel in batch_specs]
            all_examples.extend(batch_examples)

            # 6. Wersja z examples (na starej mapie duplikatów)
            save_to_output_dir({
                "merged_specification": merged_specification,
                "all_examples": all_examples,
                "duplicate_mapping": global_duplicate_mapping
            }, f'debug_input_before_combine_batch1_{batch_num + 1}.json')
            current_with_examples = combine_specifications_with_values(merged_specification, all_examples, language,
                                                                       global_duplicate_mapping)

            # 7. Analiza AI → aktualizacja mapy duplikatów
            print(f"Analiza AI dla batcha {batch_num + 1}...")
            save_to_output_dir(current_with_examples, f'input_for_ai_batch_{batch_num + 1}.json')

            try:
                batch_ai_analysis = analyze_and_save(current_with_examples, f'batch_{batch_num + 1}',
                                                     save_to_output_dir)

                if isinstance(batch_ai_analysis, dict):
                    for section, mappings in batch_ai_analysis.items():
                        # Dodatkowe sprawdzenie czy mappings jest słownikiem
                        if not isinstance(mappings, dict):
                            print(
                                f"UWAGA: Nieprawidłowy format odpowiedzi AI dla sekcji {section} w batchu {batch_num + 1}")
                            continue

                        if section not in global_duplicate_mapping:
                            global_duplicate_mapping[section] = {}

                        for canonical_name, duplicates in mappings.items():
                            # Sprawdź czy duplicates jest listą
                            if not isinstance(duplicates, list):
                                print(
                                    f"UWAGA: Nieprawidłowy format listy duplikatów dla {canonical_name} w sekcji {section}")
                                continue

                            global_duplicate_mapping[section].setdefault(canonical_name, [])
                            for duplicate in duplicates:
                                if duplicate not in global_duplicate_mapping[section][canonical_name]:
                                    global_duplicate_mapping[section][canonical_name].append(duplicate)
                else:
                    print(f"UWAGA: Nieprawidłowy format odpowiedzi AI dla batcha {batch_num + 1}")
                    save_to_output_dir({"error": "Invalid AI response format"},
                                       f'invalid_ai_response_batch_{batch_num + 1}.json')
            except Exception as e:
                print(f"BŁĄD podczas analizy AI dla batcha {batch_num + 1}: {str(e)}")
                save_to_output_dir({"error": str(e)}, f'ai_analysis_exception_batch_{batch_num + 1}.json')

            # 8. Re-normalizacja na podstawie zaktualizowanej mapy
            # Ta część wykonuje się niezależnie od wyniku analizy AI
            global_duplicate_mapping = clean_duplicate_mapping(global_duplicate_mapping)
            merged_specification = normalize_specification(merged_specification, global_duplicate_mapping)

            # 9. Nowa wersja z examples (po wyczyszczeniu duplikatów)
            save_to_output_dir({
                "merged_specification": merged_specification,
                "all_examples": all_examples,
                "duplicate_mapping": global_duplicate_mapping
            }, f'debug_input_before_combine_batch2_{batch_num + 1}.json')
            current_with_examples = combine_specifications_with_values(merged_specification, all_examples, language,
                                                                       global_duplicate_mapping)

            # 10. Zapis tylko znormalizowanych wyników
            save_to_output_dir(merged_specification, f'normalized_merged_after_batch_{batch_num + 1}.json')
            save_to_output_dir(current_with_examples, f'normalized_with_examples_after_batch_{batch_num + 1}.json')
            save_to_output_dir(global_duplicate_mapping, f'duplicate_mapping_after_batch_{batch_num + 1}.json')

    # Finalne połączenie wszystkich specyfikacji z wszystkimi przykładami
    save_to_output_dir({
        "merged_specification": merged_specification,
        "all_examples": all_examples,
        "duplicate_mapping": global_duplicate_mapping
    }, f'debug_input_before_combine_batchf_{batch_num + 1}.json')
    final_spec = combine_specifications_with_values(merged_specification, all_examples, language,
                                                    global_duplicate_mapping)

    # Zapisanie finalnych wyników
    save_to_output_dir({
        "top_level_key": "attributes",
        "secondary_key": "TVA-LCD",
        "value": merged_specification}, 'final_merged.json')
    save_to_output_dir(final_spec, 'final_with_examples.json')
    save_to_output_dir(all_specs, 'all_specs.json')

    # Oczyszczenie mapy duplikatów przed zapisaniem
    cleaned_duplicate_mapping = clean_duplicate_mapping(global_duplicate_mapping)

    save_to_output_dir(cleaned_duplicate_mapping, 'final_duplicate_mapping_cleaned.json')
    save_to_output_dir(global_duplicate_mapping, 'final_duplicate_mapping.json')

    # Finalna analiza AI
    # Definiujemy system prompt dla GPT
    system_prompt = """Przeanalizuj poniższe dane specyfikacji produktów i sprawdź, czy jakieś klucze nie zostały nadmiarowo połączone.
    Twoim zadaniem jest znalezienie atrybutów, które powinny być rozdzielone, ponieważ dotyczą różnych cech produktu.
    Zwróć finalną mapę duplikatów, ale usuń z niej wszelkie pary, które Twoim zdaniem nie powinny być łączone.
    Odpowiedź zwróć w formie JSON bez żadnych dodatkowych komentarzy czy formatowania."""

    # Przygotowujemy treść zapytania z finalną specyfikacją i mapą duplikatów
    content = f"""Oto specyfikacja produktu z przykładami:
    {json.dumps(final_spec, ensure_ascii=False, indent=2)}

    Oraz aktualna mapa duplikatów:
    {json.dumps(cleaned_duplicate_mapping, ensure_ascii=False, indent=2)}

    Jeśli uważasz, że jakieś atrybuty zostały nieprawidłowo połączone jako duplikaty, usuń je z mapy.
    Zwróć finalną, poprawioną mapę duplikatów."""

    # Wywołujemy funkcję ask_gpt_custom
    final_ai_analysis = ask_gpt_custom(system_prompt, content)

    # Próbujemy przekonwertować odpowiedź na JSON
    try:
        final_ai_mapping = json.loads(final_ai_analysis)
        save_to_output_dir(final_ai_mapping, 'final_duplicate_mapping_verified.json')
    except json.JSONDecodeError:
        print("Odpowiedź AI nie była poprawnym JSONem")
        save_to_output_dir({"raw_response": final_ai_analysis}, 'final_ai_verification_raw.json')
        final_ai_mapping = cleaned_duplicate_mapping  # Używamy oryginalnej mapy jako fallback
    # Zwracamy finalny wynik z przykładami
    return JSONResponse({
        "final_specification": final_spec,
        "merged_specification": merged_specification,
        "duplicate_mapping": cleaned_duplicate_mapping,
        "ai_analysis": final_ai_analysis,
        "output_directory": output_dir
    })

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
                    category_ids.append(
                        (category.get('categoryname_level3') if category else None)
                        or cat.get("CategoryId")
                    )
                    #    category.get('categoryname_level3') or cat.get("CategoryId"))

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


    return JSONResponse({
        "result": True
    })

