# src/routes/etl2.py
from starlette.responses import JSONResponse
import aiohttp
import asyncio
import json
import os
from src.services.ai_service import ask_gpt_custom, ask_sonoma_custom
from src.services.file_service import save_json_file
import polars as pl

import datetime
import os

def fix_json(result):
    fixed_result = result.replace("'", '"')  # Zamień pojedyncze cudzysłowy na podwójne

    # Sprawdź czy są nieparzystei liczby cudzysłowów
    if fixed_result.count('"') % 2 != 0:
        fixed_result += '"'  # Dodaj brakujący cudzysłów

    # Sprawdź nawiasy klamrowe
    if fixed_result.count('{') > fixed_result.count('}'):
        fixed_result += '}'  # Dodaj brakujący nawias zamykający

    # Spróbuj sparsować naprawiony JSON
    fixed_json = json.loads(fixed_result)
    print(f"Udało się naprawić JSON w bloku {idx + 1}")

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
    Tworzy nowy plik CSV z podmienionymi grupami typów produktów.

    Args:
        original_csv_path (str): Ścieżka do oryginalnego pliku CSV
        current_merged (dict): Słownik z grupami typów produktów w formacie:
                              {"nazwa_grupy": [["podkategoria1", "typ1"], ...], ...}
        output_dir (str): Katalog, w którym zostanie zapisany nowy plik CSV

    Returns:
        str: Ścieżka do utworzonego pliku CSV
    """
    # Wczytaj oryginalny plik CSV
    original_df = pl.read_csv(original_csv_path)

    # Stwórz odwrotne mapowanie: (Podkategoria, Typ produktu) -> Grupa typów produktu
    reverse_mapping = {}
    for group_name, items in current_merged.items():
        for item in items:
            if isinstance(item, list) and len(item) >= 2:
                subcategory, product_type = item[0], item[1]
                reverse_mapping[(subcategory, product_type)] = group_name
            elif isinstance(item, str):
                # Dla kompatybilności ze starym formatem
                reverse_mapping[(None, item)] = group_name

    # Stwórz nowy DataFrame z podmienionymi grupami
    result_data = []
    for row in original_df.iter_rows(named=True):
        subcategory = row.get('Podkategoria')
        product_type = row.get('Typ produktu')

        # Znajdź przypisaną grupę dla tej kombinacji
        new_group = reverse_mapping.get((subcategory, product_type))

        # Jeśli nie znaleziono w mapowaniu, spróbuj znaleźć po samym typie produktu
        if new_group is None:
            new_group = reverse_mapping.get((None, product_type))

        # Jeśli nadal nie znaleziono, zachowaj oryginalną wartość
        if new_group is None:
            new_group = row.get('Grupa typów produktu')

        # Stwórz nowy wiersz z podmienioną grupą
        new_row = {col: row.get(col) for col in original_df.columns}
        new_row['Grupa typów produktu'] = new_group

        result_data.append(new_row)

    # Utwórz nowy DataFrame i zapisz do CSV
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


async def group_types(request):
    # Utworzenie katalogu wyjściowego
    output_dir = create_output_directory()

    # Funkcja pomocnicza do zapisywania plików w katalogu wyjściowym
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    types_blocks = split_csv_to_blocks('data/typy3.csv', block_size=50, output_directory=output_dir)

    system_prompt = """
    Jesteś ekspertem w grupowaniu i kategoryzowaniu typów produktów.
    """
    current_merged = {}

    for idx, block in enumerate(types_blocks):
        user_prompt = f"""
        Masz tabelę z kolumnami: Kategoria, Podkategoria, Typ produktu, Grupy typów produktu.

        Twoim zadaniem jest zwrócić JSON z dwoma kluczami:

        1️⃣ "groups": wszystkie unikalne kombinacje (Podkategoria, Typ produktu) w osobnych podlistach.
           - Każda kombinacja musi być w JSON-ie.
           - Nazwy grup **muszą być opisowe i precyzyjne**, tak aby różne rodzaje akcesoriów lub produktów nie były scalane.
           - **Nie używaj placeholderów** typu 'inna_grupa', 'grupa1', 'nowa_grupa'.
           - Nie grupuj wg podobieństwa ani synonimów, nie zgaduj powiązań poza istniejącymi grupami.

        2️⃣ "move_groups": lista istniejących grup, które mogą zostać przeniesione do nowo powstałej grupy nadrzędnej (opcjonalnie, możesz pozostawić puste).

        Masz dostęp do istniejących grup: {current_merged.keys()}.
        - Jeśli kombinacja pasuje do istniejącej grupy, przypisz ją tam.
        - Jeśli nie, stwórz nową grupę z opisową nazwą.

        Zwróć wyłącznie JSON w tym formacie:

        {{
          "groups": {{
              "Akcesoria do grillowania": [["Grillowanie", "Akcesoria"]],
              "Adaptery sieciowe": [["Sieci i systemy zabezpieczeń", "AccesPoint"]],
              ...
          }},
          "move_groups": {{
              "Akcesoria rowerowe": ["Akcesoria uniwersalne"]
          }}
        }}

        Tabela wejściowa:
        {block.write_csv(separator="\t")}
        """

        try:
            # Wywołanie synchroniczne bez asyncio.run_in_executor
            result = ask_gpt_custom(system_prompt, user_prompt, model="gpt-4.1")

            # Zapisz surową odpowiedź (do celów diagnostycznych)
            save_to_output_dir({"raw_response": result}, f"block_{idx + 1}_raw_response.json")

            # Próba parsowania JSON
            try:
                result_json = json.loads(result)

                # Zapisz poprawnie sparsowany JSON
                save_to_output_dir(result_json, f"block_{idx + 1}_parsed.json")

                # Oblicz statystyki
                items_count = sum([len(r) for r in result_json['groups'].values() if isinstance(r, list)])
                print(f"Blok {idx + 1}: znaleziono {items_count} elementów w {len(result_json['groups'])} grupach")

                # Aktualizuj merged
                current_merged = merge_product_type_groups([current_merged, result_json['groups']])

                # Obsługa move_groups z przekazaniem odpowiednich danych
                if 'move_groups' in result_json and isinstance(result_json['move_groups'], dict):
                    current_merged = merge_groups(current_merged, result_json['move_groups'])

                save_to_output_dir(current_merged, "current_merged.json")

            except json.JSONDecodeError as e:
                print(f"Błąd parsowania JSON w bloku {idx + 1}: {e}")
                # Zapisz informacje o błędzie
                error_info = {
                    "error": str(e),
                    "raw_response": result,
                    "error_position": {
                        "line": e.lineno,
                        "column": e.colno,
                        "char_position": e.pos
                    }
                }
                save_to_output_dir(error_info, f"block_{idx + 1}_error.json")

                # Możemy spróbować naprawić najczęstsze problemy z JSON
                try:
                    fixed_json = fix_json(result)

                    # Zapisz naprawiony JSON
                    save_to_output_dir(fixed_json, f"block_{idx + 1}_fixed.json")

                    # Aktualizuj merged z naprawionym JSON
                    if 'groups' in fixed_json:
                        current_merged = merge_product_type_groups([current_merged, fixed_json['groups']])

                        if 'move_groups' in fixed_json and isinstance(fixed_json['move_groups'], dict):
                            current_merged = merge_groups(current_merged, fixed_json['move_groups'])
                    else:
                        # Jeśli nie ma klucza 'groups', traktuj cały JSON jako grupy
                        current_merged = merge_product_type_groups([current_merged, fixed_json])

                    save_to_output_dir(current_merged, "current_merged.json")

                except Exception as fix_error:
                    print(f"Nie udało się naprawić JSON: {fix_error}")
                    # Kontynuuj z następnym blokiem

        except Exception as e:
            print(f"Błąd podczas przetwarzania bloku {idx + 1}: {e}")
            save_to_output_dir({"error": str(e)}, f"block_{idx + 1}_processing_error.json")

    # Utwórz plik CSV z nowymi grupami
    try:
        output_csv_path = create_updated_csv('data/typy3.csv', current_merged, output_dir)
        print(f"Utworzono plik CSV z nowymi grupami: {output_csv_path}")
    except Exception as e:
        print(f"Błąd podczas tworzenia pliku CSV: {e}")
        save_to_output_dir({"error": str(e)}, "csv_creation_error.json")

    return JSONResponse({
        'success': True,
        'output_directory': output_dir,
        'groups_count': len(current_merged),
        'final_csv': os.path.join(output_dir, "typy_new_groups.csv")
    })