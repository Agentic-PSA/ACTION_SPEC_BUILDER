# src/routes/etl2.py
import datetime
import json
import os

import polars as pl
from starlette.responses import JSONResponse

from src.services.ai_service import ask_gpt_custom
from src.services.file_service import save_json_file


def fix_json(result, idx=None):
    """
    Naprawia niepoprawny JSON.

    Args:
        result (str): Tekst JSON do naprawy
        idx (int, optional): Indeks bloku dla celów logowania

    Returns:
        dict: Naprawiony obiekt JSON
    """
    fixed_result = result.replace("'", '"')  # Zamień pojedyncze cudzysłowy na podwójne

    # Sprawdź czy są nieparzystei liczby cudzysłowów
    if fixed_result.count('"') % 2 != 0:
        fixed_result += '"'  # Dodaj brakujący cudzysłów

    # Sprawdź nawiasy klamrowe
    if fixed_result.count('{') > fixed_result.count('}'):
        fixed_result += '}'  # Dodaj brakujący nawias zamykający

    # Spróbuj sparsować naprawiony JSON
    fixed_json = json.loads(fixed_result)
    if idx is not None:
        print(f"Udało się naprawić JSON w bloku {idx + 1}")
    else:
        print("Udało się naprawić JSON")

    return fixed_json

def split_csv_to_blocks(file_path, block_size=30, output_directory=None, sort_column=2):
    """
    Loads a CSV file, sorts it by the specified column and splits it into smaller blocks
    with header and specified number of rows using polars library.

    Args:
        file_path (str): Path to the CSV file
        block_size (int): Number of data rows in each block (default 30)
        output_directory (str): Optional directory to save the resulting blocks
                               If None, returns a list of dataframes
        sort_column (int): Column index to sort by (0-based, default 2 for third column)

    Returns:
        list or None: List of data blocks (DataFrame) or None if saved to files
    """
    # Load the entire CSV file
    df = pl.read_csv(file_path)

    # Sort the dataframe by the specified column
    sort_col_name = df.columns[sort_column]
    df = df.sort(sort_col_name)

    # Calculate the number of full blocks
    row_count = df.height
    block_count = (row_count + block_size - 1) // block_size

    # Create blocks
    blocks = []
    for i in range(block_count):
        start = i * block_size
        end = min((i + 1) * block_size, row_count)
        block = df.slice(start, end - start)
        blocks.append(block)

    # If output directory is provided, save blocks to CSV files
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)
        file_name = os.path.basename(file_path).split('.')[0]

        for i, block in enumerate(blocks):
            block_name = f"{file_name}_block_{i + 1}.csv"
            output_path = os.path.join(output_directory, block_name)
            block.write_csv(output_path)

    # Otherwise return the list of blocks
    return blocks


def create_output_directory():
    """
    Tworzy folder wyjściowy na podstawie bieżącej daty i godziny.

    Returns:
        str: Ścieżka do utworzonego katalogu
    """
    now = datetime.datetime.now()
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = os.path.join("output2", timestamp)

    # Tworzenie katalogu, jeśli nie istnieje
    os.makedirs(output_dir, exist_ok=True)

    print(f"Utworzono katalog wyjściowy: {output_dir}")
    return output_dir


def merge_product_type_groups(results_dict_list):
    """
    Łączy wyniki grupowania typów produktów z wielu zapytań.

    Obsługuje format danych:
    {"nazwa_grupy": [["podkategoria1", "typ1"], ["podkategoria2", "typ2"]], ...}

    Args:
        results_dict_list (list): Lista słowników zawierających grupy produktów

    Returns:
        dict: Połączony słownik grup produktów bez duplikatów
    """
    merged_results = {}

    for result_dict in results_dict_list:
        if not isinstance(result_dict, dict):
            continue

        for group_name, items in result_dict.items():
            if not isinstance(items, list):
                continue

            if group_name in merged_results:
                # Dla każdego elementu w obecnym wyniku
                for item in items:
                    # Sprawdź, czy element już istnieje w połączonych wynikach
                    item_exists = False
                    for existing_item in merged_results[group_name]:
                        # Porównaj pary [podkategoria, typ]
                        if isinstance(item, list) and isinstance(existing_item, list) and len(item) > 1 and len(
                                existing_item) > 1:
                            if item[1] == existing_item[1]:  # Porównanie po typie produktu (drugi element)
                                item_exists = True
                                break
                        elif item == existing_item:  # Dla kompatybilności wstecznej
                            item_exists = True
                            break

                    # Jeśli element nie istnieje, dodaj go
                    if not item_exists:
                        merged_results[group_name].append(item)
            else:
                # Jeśli grupa nie istnieje, utwórz nową
                merged_results[group_name] = items.copy() if isinstance(items, list) else [items]

    return merged_results


def create_updated_csv(original_csv_path, current_merged, output_dir):
    """
    Tworzy nowy plik CSV z podmienionymi grupami typów produktów i dodatkową kolumną
    informującą, czy grupa pochodzi z nowych danych (1) czy ze starej kolumny (0).
    """
    import polars as pl
    import os

    # Wczytaj oryginalny plik CSV
    original_df = pl.read_csv(original_csv_path)

    # Odwrotne mapowanie: (Podkategoria, Typ produktu) -> Grupa typów produktu
    reverse_mapping = {}
    for group_name, items in current_merged.items():
        for item in items:
            if isinstance(item, list) and len(item) >= 2:
                subcategory, product_type = item[0], item[1]
                reverse_mapping[(subcategory, product_type)] = group_name

    result_data = []
    for row in original_df.to_dicts():
        subcategory = row.get('Podkategoria')
        product_type = row.get('Typ produktu')
        original_group = row.get('Grupy typów produktu')

        # Szukamy grupy w reverse_mapping
        new_group = reverse_mapping.get((subcategory, product_type))
        is_new = 1 if new_group else 0  # 1 = nowa grupa, 0 = stara

        # Jeśli nie znaleziono w mapowaniu, użyj oryginalnej grupy
        if not new_group:
            new_group = original_group

        new_row = row.copy()
        new_row['Proponowane typy'] = new_group
        new_row['Nowa grupa'] = is_new  # 1 = nowa, 0 = stara
        result_data.append(new_row)

    # Utwórz DataFrame i zapisz CSV
    new_df = pl.DataFrame(result_data)
    output_csv_path = os.path.join(output_dir, "typy_new_groups.csv")
    new_df.write_csv(output_csv_path)

    return output_csv_path



def merge_groups(current_merged, move_groups_data):
    """
    Przenosi elementy z grup podrzędnych do nadrzędnych zgodnie z danymi w move_groups_data.

    Args:
        current_merged (dict): Słownik zawierający grupy typów produktów
        move_groups_data (dict): Słownik w formacie {grupa_nadrzędna: [grupy_podrzędne]}

    Returns:
        dict: Zaktualizowany słownik z przeniesionymi grupami
    """
    for parent_group, child_groups in move_groups_data.items():
        if isinstance(child_groups, list):
            for child_group in child_groups:
                # Sprawdź czy obie grupy istnieją
                if parent_group in current_merged and child_group in current_merged:
                    # Przenieś elementy z grupy dziecka do grupy rodzica
                    current_merged[parent_group].extend(current_merged[child_group])
                    # Usuń grupę dziecka
                    del current_merged[child_group]
                    print(f"Przeniesiono grupę '{child_group}' do nadrzędnej '{parent_group}'")
    return current_merged

def find_hallucinations(combined_groups, block):
    """
    Zwraca dict z halucynacjami:
    {
      "nazwa_grupy": [["Podkategoria", "Typ produktu"], ...]
    }
    """
    # wszystkie dozwolone pary z tabeli
    available = set(
        (row["Podkategoria"], row["Typ produktu"])
        for _, row in block.iterrows()
    )

    hallucinations = {}
    for gname, items in combined_groups.items():
        for podkat, typ in items:
            if (podkat, typ) not in available:
                hallucinations.setdefault(gname, []).append([podkat, typ])
    return hallucinations

def classify_block(system_prompt, block, current_merged, idx, save_fn):
    user_prompt = f"""
Masz tabelę z kolumnami: Kategoria, Podkategoria, Typ produktu, Grupy typów produktu.

Twoim zadaniem jest zwrócić JSON z dwoma kluczami:

1️⃣ "groups": wszystkie unikalne kombinacje (Podkategoria, Typ produktu), które **nie pasują do żadnej z istniejących grup**.
   - Każda kombinacja musi być w JSON-ie.
   - Nazwy grup muszą być opisowe i precyzyjne (np. "Akcesoria do grillowania", "Adaptery sieciowe").
   - Nie używaj placeholderów typu 'inna_grupa', 'grupa1', 'nowa_grupa'.

2️⃣ "old_groups": wszystkie kombinacje, które wyglądają jakby należały do którejś z istniejących grup.
   - Lista istniejących grup: {current_merged.keys()}.
   - Jeśli kombinacja pasuje do którejś z tych grup, dodaj ją do "old_groups" zamiast do "groups".

⚠️ Każda kombinacja z tabeli musi trafić dokładnie do jednej kategorii: "groups" albo "old_groups".
⚠️ Kolumna "Grupy typów produktu" z tabeli jest tylko luźną wskazówką – nie traktuj jej jako prawdy.
⚠️ Nie łącz różnych rodzajów akcesoriów ani produktów w jedną grupę (np. grillowanie ≠ łazienka ≠ rowery).

Zwróć wyłącznie JSON w tym formacie:

{{
  "groups": {{
      "Akcesoria do grillowania": [["Grillowanie", "Akcesoria"]],
      "Adaptery sieciowe": [["Sieci i systemy zabezpieczeń", "AccesPoint"]]
  }},
  "old_groups": {{
      "Akcesoria do laptopów": [["IT", "Akcesoria"]],
      "Adaptery audio": [["Mikrofony i słuchawki", "Adaptery i przejściówki"]]
  }}
}}

Tabela wejściowa:
{block.write_csv(separator="\t")}
"""

    try:
        save_prompt(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}",
                    "classify", idx, os.path.dirname(save_fn({}, "dummy.json")))
        result = ask_gpt_custom(system_prompt, user_prompt, model="gpt-4.1")
        save_fn({"raw_response": result}, f"block_{idx + 1}_raw_response.json")
        print('NEW')
        return json.loads(result)
    except Exception as e:
        save_fn({"error": str(e)}, f"block_{idx + 1}_classify_error.json")
        return None


def handle_old_groups(system_prompt, result_json, current_merged, idx, save_fn, merge=True):
    # Jeśli nie ma old_groups, tylko update
    if 'old_groups' not in result_json or not result_json['old_groups']:
        return {}, current_merged  # brak old_groups → nic nie robimy

        # Zbuduj kontekst grup
    groups_context = build_groups_context(result_json['old_groups'], current_merged)

    old_groups = result_json["old_groups"]
    reclassify_prompt = f"""
Mam zestaw produktów, które trzeba przypisać do istniejących grup lub utworzyć dla nich nowe grupy.

ISTNIEJĄCE GRUPY (z przykładami), które mogą być odpowiednie:
{json.dumps(groups_context, indent=2, ensure_ascii=False)}

PRODUKTY DO KLASYFIKACJI:
{json.dumps(old_groups, indent=2, ensure_ascii=False)}

Przypisz każdy produkt do odpowiedniej istniejącej grupy z powyższej listy. 
Jeśli produkt nie pasuje do żadnej z tych grup, stwórz nową grupę z opisową nazwą.
Nie używaj placeholderów jak 'inna_grupa' czy 'nowa_grupa'.

Zwróć JSON tylko z kluczem "groups", gdzie każdy produkt jest przypisany do dokładnie jednej grupy:

{{
  "groups": {{
    "Nazwa grupy 1": [["Podkategoria1", "Typ1"], ...],
    "Nazwa grupy 2": [["Podkategoria2", "Typ2"], ...]
  }}
}}
"""
    save_prompt(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{reclassify_prompt}",
                "old", idx, os.path.dirname(save_fn({}, "dummy.json")))
    reclassify_result = ask_gpt_custom(system_prompt, reclassify_prompt, model="gpt-4.1")
    save_fn({"raw_reclassify_response": reclassify_result}, f"block_{idx + 1}_reclassify_raw.json")

    try:
        reclassify_json = json.loads(reclassify_result)
        save_fn(reclassify_json, f"block_{idx + 1}_reclassified.json")

        if 'groups' in reclassify_json:
            reclassified_count = sum(len(v) for v in reclassify_json['groups'].values())
            print(f"Blok {idx + 1}: Reklasyfikowano {reclassified_count} elementów")
            return reclassify_json['groups'], current_merged
        else:
            print(f"Blok {idx + 1}: Brak 'groups' w reklasyfikacji")
            return {}, current_merged
    except json.JSONDecodeError as e:
        print(f"Błąd parsowania JSON reklasyfikacji w bloku {idx + 1}: {e}")
        return {}, current_merged


def save_prompt(prompt, prompt_type, idx, output_dir):
    """
    Zapisuje prompt do pliku tekstowego dla celów dokumentacji.

    Args:
        prompt (str): Treść promptu
        prompt_type (str): Rodzaj promptu (np. 'classify', 'reclassify', 'validate')
        idx (int): Indeks bloku
        output_dir (str): Katalog wyjściowy
    """
    prompt_dir = os.path.join(output_dir, "prompts")
    os.makedirs(prompt_dir, exist_ok=True)

    filename = f"block_{idx + 1}_{prompt_type}_prompt.txt"
    filepath = os.path.join(prompt_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(prompt)

    return filepath

def validate_with_agent3(groups_from_agent1, groups_from_agent2, block, system_prompt, idx, save_fn):
    combined_groups = {**groups_from_agent1, **groups_from_agent2}

    validation_prompt = f"""
Masz oryginalną tabelę typów produktów:

{block.write_csv(separator="\t")}

Masz też propozycje grupowania z wcześniejszych kroków:

{json.dumps(combined_groups, indent=2, ensure_ascii=False)}

Twoje zadania:
Struktura grup z poprzednich kroków wygląda tak:

['nowa_grupa1': [['Podkategoria', 'Typ produktu'], ...], 'nowa_grupa2': [...], ...]

1. Sprawdź, czy w tych grupach pojawiły się elementy zmyślone, których nie ma w tabeli wejściowej → umieść je w kluczu "hallucinations".
2. Kolumna "Grupy typów produktu" z tabeli jest tylko luźną wskazówką – nie traktuj jej jako prawdy.
3. Sprawdź, które elementy z tabeli wejściowej zostały pominięte. Dla tych elementów **stwórz nowe propozycje grupowania** i umieść je wyłącznie w kluczu "groups".
   - **Nie zmieniaj istniejących grup ani ich zawartości.**
   - Do "groups" trafiają tylko elementy, które brakują w dotychczasowych grupach.

Wynikowy JSON:

{{
  "groups": {{
    "Nazwa nowej grupy": [["Podkategoria", "Typ produktu"], ...]
  }},
  "hallucinations": {{"grupa":["Podkategoria", "Typ produktu"], ...}},
}}
"""

    save_prompt(f"SYSTEM:\n{system_prompt}\n\nUSER:\n{validation_prompt}",
                              "halu", idx, os.path.dirname(save_fn({}, "dummy.json")))

    validation_result = ask_gpt_custom(system_prompt, validation_prompt, model="gpt-4.1")
    save_fn({"raw_validation_response": validation_result}, f"block_{idx + 1}_validation_raw.json")

    try:
        validation_json = json.loads(validation_result)
        save_fn(validation_json, f"block_{idx + 1}_validated.json")

        hallucinations = validation_json.get("hallucinations", {})
        missing = validation_json.get("missing", [])
        groups_for_missing = validation_json.get("groups", {})

        print(f"Blok {idx + 1}: Walidacja – {len(hallucinations)} halucynacji, {len(missing)} brakujących elementów, {sum(len(v) for v in groups_for_missing.values())} propozycji")

        return groups_for_missing, hallucinations, missing

    except json.JSONDecodeError as e:
        print(f"Błąd parsowania JSON walidacji w bloku {idx + 1}: {e}")
        return {}, [], []

def build_groups_context(current_merged, old_groups):
    referenced_groups = set()
    for items in old_groups.values():
        for item in items:
            if isinstance(item, list) and len(item) >= 2:
                subcategory, product_type = item[:2]
                for group_name, group_items in current_merged.items():
                    if any(
                            (subcategory in gi[0] or gi[0] in subcategory or
                             product_type in gi[1] or gi[1] in product_type)
                            for gi in group_items if isinstance(gi, list) and len(gi) >= 2
                    ):
                        referenced_groups.add(group_name)

    groups_context = {g: current_merged[g][:5] for g in referenced_groups if g in current_merged}

    if not groups_context:
        # jeśli brak dopasowania, dodaj kilka ostatnich
        recent = list(current_merged.keys())[-10:]
        groups_context = {g: current_merged[g][:5] for g in recent}

    return groups_context


def remove_hallucinations(groups_dict, hallucinations):
    """
    Usuwa halucynacje z grup.

    Args:
        groups_dict (dict): Słownik z grupami
        hallucinations (dict/list): Halucynacje do usunięcia (w nowym formacie jako słownik lub starym jako lista)

    Returns:
        dict: Nowy słownik bez halucynacji
    """
    cleaned = {}

    # Przekształć halucynacje do jednolitego formatu do porównania
    hallucination_strings = set()

    # Obsługa nowego formatu (słownik)
    if isinstance(hallucinations, dict):
        for item_list in hallucinations.values():
            if isinstance(item_list, list):
                for item in item_list:
                    hallucination_strings.add(str(item))
            else:
                print(f"UWAGA: wartość w słowniku hallucinations nie jest listą: {item_list}")

    # Obsługa starego formatu (lista)
    elif isinstance(hallucinations, list):
        for item in hallucinations:
            if isinstance(item, list):
                hallucination_strings.add(str(item))
            else:
                print(f"UWAGA: element hallucinations nie jest listą: {item}")
    else:
        print(f"UWAGA: hallucinations nie jest ani listą, ani słownikiem ({type(hallucinations)})")
        return groups_dict

    # Filtruj grupy
    for group_name, items in groups_dict.items():
        cleaned_items = []
        for i in items:
            if isinstance(i, list) and str(i) not in hallucination_strings:
                cleaned_items.append(i)
            elif not isinstance(i, list):
                # Jeśli to nie jest lista, po prostu zachowaj
                cleaned_items.append(i)

        if cleaned_items:
            cleaned[group_name] = cleaned_items

    return cleaned



async def group_types(request):
    output_dir = create_output_directory()

    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    types_blocks = split_csv_to_blocks('data/typy3.csv', block_size=30, output_directory=output_dir)
    system_prompt = "Jesteś ekspertem w grupowaniu i kategoryzowaniu typów produktów."
    current_merged = {}

    for idx, block in enumerate(types_blocks):
        # --- Etap 1: klasyfikacja bloku ---
        result_json = classify_block(system_prompt, block, current_merged, idx, save_to_output_dir)
        save_to_output_dir(result_json, f"block_{idx + 1}_response.json")
        if not result_json:
            continue

        items_count = sum(len(r) for r in result_json['groups'].values() if isinstance(r, list))
        print(f"Blok {idx + 1}: znaleziono {items_count} elementów w {len(result_json['groups'])} nowych grupach")

        # --- Etap 2: reklasyfikacja old_groups (ale jeszcze NIE mergujemy) ---
        groups_stage2, _ = handle_old_groups(
            system_prompt, result_json, current_merged, idx, save_to_output_dir, merge=False
        )

        # --- Etap 3: walidacja (hallucinations + missing) ---
        groups_stage3, hallucinations, missing = validate_with_agent3(
            result_json["groups"], groups_stage2, block, system_prompt, idx, save_to_output_dir
        )

        # --- Scalanie po walidacji ---
        groups_stage1_clean = remove_hallucinations(result_json["groups"], hallucinations)
        groups_stage2_clean = remove_hallucinations(groups_stage2, hallucinations)

        merged_groups = merge_product_type_groups([
            groups_stage1_clean,
            groups_stage2_clean,
            groups_stage3
        ])

        # --- Update current_merged ---
        current_merged = merge_product_type_groups([current_merged, merged_groups])



        save_to_output_dir(current_merged, "current_merged.json")

    # --- Generowanie końcowego CSV ---
    try:
        output_csv_path = create_updated_csv('data/typy3.csv', current_merged, output_dir)
        print(f"Utworzono plik CSV z nowymi grupami: {output_csv_path}")
    except Exception as e:
        print(f"Błąd CSV: {e}")
        save_to_output_dir({"error": str(e)}, "csv_creation_error.json")

    return JSONResponse({
        'success': True,
        'output_directory': output_dir,
        'groups_count': len(current_merged),
        'final_csv': os.path.join(output_dir, "typy_new_groups.csv")
    })

