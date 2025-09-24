# src/routes/etl2.py
from starlette.responses import JSONResponse
import aiohttp
import asyncio
import json
import os
from src.services.ean_service import read_eans, send_message, is_ean_valid, generate_ean_variants, read_eans_from_file
from src.services.specification_service import merge_specifications, combine_specifications_with_values, normalize_specification 
from src.services.ai_service import analyze_and_save, ai_analyze_and_create_form, ai_add_main_data, ai_remove_duplicates, ai_set_order
from src.services.file_service import save_json_file

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
    Usuwa z listy duplikatów nazwy identyczne z kluczami kanonicznymi,
    rozwija łańcuchy duplikatów do najwyższego kanonicznego
    oraz zachowuje puste klucze.

    Args:
        duplicate_mapping (dict): Mapa duplikatów do oczyszczenia

    Returns:
        dict: Oczyszczona mapa duplikatów
    """
    # Budujemy odwrotną mapę: duplikat -> kanoniczny
    reverse_mapping = {}
    for section, mappings in duplicate_mapping.items():
        for canonical_name, duplicates in mappings.items():
            for dup in duplicates:
                reverse_mapping.setdefault(section, {})[dup] = canonical_name

    def resolve_target(section, name):
        """Znajdź najwyższy kanoniczny klucz dla danego duplikatu."""
        seen = set()
        while name in reverse_mapping.get(section, {}) and name not in seen:
            seen.add(name)
            name = reverse_mapping[section][name]
        return name

    cleaned_mapping = {}
    for section, mappings in duplicate_mapping.items():
        cleaned_mapping[section] = {}
        for canonical_name, duplicates in mappings.items():
            target = resolve_target(section, canonical_name)

            # przerzucamy wszystkie duplikaty do najwyższego kanonicznego
            for dup in duplicates:
                dup_target = resolve_target(section, dup)
                if dup_target != target and dup != target:
                    cleaned_mapping[section].setdefault(target, []).append(dup_target)

            # dopilnuj, żeby kanoniczny klucz istniał w mapie
            cleaned_mapping[section].setdefault(target, [])

    # deduplikacja i zachowanie kolejności
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
    final_ai_analysis = analyze_and_save(final_spec, 'final', save_to_output_dir, final=True)

    # Zwracamy finalny wynik z przykładami
    return JSONResponse({
        "final_specification": final_spec,
        "merged_specification": merged_specification,
        "duplicate_mapping": cleaned_duplicate_mapping,
        "ai_analysis": final_ai_analysis,
        "output_directory": output_dir
    })

async def etl2_create_spec_aka(request):
    # Utworzenie katalogu wyjściowego
    output_dir = create_output_directory()

    # Funkcja pomocnicza do zapisywania plików w katalogu wyjściowym
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    #data_lcd = await read_eans_from_file('data/TVA-LCD.json')
    #data_oled = await read_eans_from_file('data/TVA-OLE.json')
    #data_lcd = await read_eans_from_file('data/AGD-EXP.json')
    #data_oled = await read_eans_from_file('data/AGD-EXZ.json')
    #data = {**{d['gtin']: d for d in data_lcd}, **{d['gtin']: d for d in data_oled}}

    # telewizory
    # files = [
    #     'data/TVA-LCD.json',
    #     'data/TVA-OLE.json',
    # ]
    # grzejniki
    # files = [
    #     'data/AGD-GKO.json',
    #     'data/AGD-GRO.json',
    # ]
    # golarki
    files = [
        'data/AGD-GOL.json',
        'data/AGD-GDU.json',
        'data/AGD-STR.json',
    ]
    category_desc = "Golarki"
    data = {}

    for file_path in files:
        records = await read_eans_from_file(file_path)
        data.update({d['gtin']: d for d in records})

    connector = aiohttp.TCPConnector(limit=30)

    async with aiohttp.ClientSession(connector=connector) as session:
        all_params = {}
        translates = {}
        params_for_categories = {}
        products = {}
        total = len(data)
        ai_cnt = 0
        total = 2

        for i, (k, v) in enumerate(data.items(), start=1):
            if i > total:
                break
            result = await process_single_ean(session, i, total, i, v)
            if not result:
                continue
            params = result['panel']["specification_values"]["PL"]
            products[v['gtin']] = params
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
                            if v['groupId'] not in params_for_categories[category][key_to_use]:
                                params_for_categories[category][key_to_use].append(v['groupId'])
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
                    print(f"Analiza AI {ai_cnt}")
                    #def ai_analyze_and_create_form(category, section, current_structure, data, filename_prefix, save_function, final=False, max_attempts=2):
                    ai_analysis = ai_analyze_and_create_form(category_desc, category, all_params[category], params, f'item_{i}', save_to_output_dir)
                    #print(ai_analysis)
                    if ai_analysis:
                        for par, val in ai_analysis.items():
                            if val == 'NOWA':
                                all_params[category][par] = potential_new[category][par]
                                if par not in params_for_categories[category]:
                                    params_for_categories[category][par] = []
                                if v['groupId'] not in params_for_categories[category][par]:
                                    params_for_categories[category][par].append(v['groupId'])

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
                                if v['groupId'] not in params_for_categories[category][par]:
                                    params_for_categories[category][par].append(v['groupId'])
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

        # usuń duplikaty
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

        # ustal kolejność
        ordered = ai_set_order(category_desc, all_params, f'ordered', save_to_output_dir)
        save_to_output_dir(ordered, f'zz_all_params_with_order')

        # stwórz dane podstawowe i oczyść z danych przykładowych
        main_data = ai_add_main_data(category_desc, ordered, f'main_data', save_to_output_dir)
        main_data = {
            "Dane podstawowe": main_data
        }
        save_to_output_dir(main_data, f'zz_all_params_with_main_data')
        without_examples = {category: list(params.keys()) for category, params in all_params.items()}
        final_specs = {**main_data, **without_examples}
        #main_data_wihout_examples = {category: list(params.keys()) for category, params in main_data.items()}
        #final_specs = {**main_data_wihout_examples, **without_examples}
        save_to_output_dir(final_specs, f'zz_specs_final')
        

    return JSONResponse({
        "result": True
    })

