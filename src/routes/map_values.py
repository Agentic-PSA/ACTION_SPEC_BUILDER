import datetime
import json
import os
import psycopg2
import psycopg2.extras
from collections import Counter
import polars as pl
from starlette.responses import JSONResponse

from src.services.ai_service import ask_gpt_custom, ask_sonoma_custom
from src.services.file_service import save_json_file


def get_form_data(category: str):
    """
    Pobiera dane formularza z bazy danych PostgreSQL dla podanej kategorii.

    Args:
        category (str): kategoria rekordu do pobrania

    Returns:
        tuple: (category, form_with_values)
    """
    try:
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST"),
            port=os.environ.get("POSTGRES_PORT"),
            database=os.environ.get("POSTGRES_DB"),
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD")
        )

        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(
            "SELECT category, form_with_values FROM forms WHERE category = %s LIMIT 1",
            [category]
        )
        result = cursor.fetchone()

        if result:
            return result["category"], result["form_with_values"]
        else:
            raise ValueError(f"Brak danych w tabeli forms dla kategorii '{category}'")

    except Exception as e:
        print(f"Błąd podczas pobierania danych z bazy: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()





def update_form_values_map(form_id, final_map):
    """
    Aktualizuje kolumnę values_map w tabeli forms dla podanego rekordu.

    Args:
        form_id (int): ID rekordu do aktualizacji
        final_map (dict): wyliczony final_map do zapisania w values_map
    """
    try:
        conn = psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST"),
            port=os.environ.get("POSTGRES_PORT"),
            database=os.environ.get("POSTGRES_DB"),
            user=os.environ.get("POSTGRES_USER"),
            password=os.environ.get("POSTGRES_PASSWORD")
        )
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE forms SET values_map = %s WHERE category = %s",
            [json.dumps(final_map), form_id]
        )
        conn.commit()
        print(f"✅ Zaktualizowano rekord ID={form_id} w kolumnie values_map")

    except Exception as e:
        print(f"Błąd podczas aktualizacji: {e}")
        raise

    finally:
        if 'conn' in locals() and conn:
            cursor.close()
            conn.close()


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

def normalize_values(original_map, final_map):
    """
    Dla każdej sekcji/parametru:
    - buduje słownik original_value -> normalized_value (pomijając przypadki orig == norm),
    - przechodzi listę wartości z oryginalnych danych i:
        * jeśli wartość jest zmapowana -> podstawia normalized_value,
        * jeśli nie -> zostawia wartość oryginalną,
        * usuwa duplikaty, zachowując kolejność.
    """
    normalized_map = {}
    for section, params in original_map.items():
        normalized_map[section] = {}
        for param, values in params.items():
            orig_to_norm = {}
            if section in final_map and param in final_map[section]:
                # final_map[section][param]['values'] = {norm_val: [orig1, orig2, ...]}
                for norm_val, orig_vals in final_map[section][param]['values'].items():
                    for ov in orig_vals:
                        if ov != norm_val:  # pomijamy mapowania identyczne
                            orig_to_norm[ov] = norm_val

            # zamiana z oryginalnych danych
            result = []
            seen = set()
            for v in values:
                new_v = orig_to_norm.get(v, v)
                if new_v not in seen:
                    result.append(new_v)
                    seen.add(new_v)

            normalized_map[section][param] = result
    return normalized_map

async def map_values(request):
    data = await request.json()
    return await map_values_logic(data)

async def map_values_logic(data):
    output_dir = create_output_directory()
    print('test')
    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path

    #data = await request.json()  # <- to zwraca dict
    category = data.get("category")
    if not category:
        return JSONResponse({'error': 'Brak kategorii w żądaniu'}, status_code=400)
    record_id, premap_vals = get_form_data(category)

    map_vals = {}
    for section in premap_vals[0]['value']:
        if section['section_name']['PL'] == 'Dane podstawowe':
            continue
        # if section['section_name']['PL'] == 'Oczyszczone':
        #     continue
        # if section['section_name']['PL'] == 'Dane podstawowe':
        #     map_vals[section['section_name']['PL']] = {p['PL']: p['values'] for p in section['attributes'] if p['PL'] == 'Model wbudowanej karty graficznej'}
        map_vals[section['section_name']['PL']] = {p['PL']: p['values'] for p in section['attributes']}
    # if True:
    #     return JSONResponse(map_values)
    # with open('data/all_params_after_449.json', 'r', encoding='utf-8') as file:
    #     map_vals = json.load(file)
    MAX_LENGTH = 40
    blocks = [{'length': 0, 'items': {}}]
    llm_map = {}
    for map in map_vals.items():
        for k,v  in map[1].items():
            # if len(v)<2:
            #     if map[0] not in llm_map:
            #         llm_map[map[0]] = {}
            #     llm_map[map[0]][k] = {_v: [_v] for _v in v}
            #     continue
            if len(v)+ blocks[-1]['length'] > MAX_LENGTH and blocks[-1]['length'] > 0:
                blocks.append({'length': 0, 'items': {}})
            blocks[-1]['length'] += len(v)
            if map[0] not in blocks[-1]['items']:
                blocks[-1]['items'][map[0]] = {}
            blocks[-1]['items'][map[0]][k] = v
    save_json_file(blocks, os.path.join(output_dir,'map_values.json'))
    system_prompt = """Jesteś asystentem, który pomaga w normalizacji wypełnień parametrów produktów. W aplikacji magazynowej."
    """

    for idx, block in enumerate(blocks):
        user_prompt = f"""
        Twoje zadanie polega na:
        1. Usunięciu duplikatów w wartościach atrybutów.
        2. Jeśli wartości różnią się tylko formatem (np. cal/cm, zapis liczbowy z przecinkiem/kropką, nawiasy) → ujednolić do jednego formatu.
        3. Jeśli wartości są bardzo zbliżone (np. wynik konwersji jednostek, różnice z zaokrągleń, minimalne różnice po przecinku <1% wartości) → potraktować jako duplikaty i zostawić tylko jedną reprezentatywną wartość.
        4. Pojedyncza jednostka wartości nie może być wartością znormalizowaną, błędem jest przypisanie wartości (200 kWh, 300 kWh, 400 kWh) do znormalizowanej wartości (kWh).
        5. Utworzeniu wspólnych wartości dla kilku nazw oznaczających to samo (np. „Direct-LED BLU” = „Direct-LED”, lub ""4K Ultra HD" = "Ultra HD").
        6. Poprawieniu wszystkich wartości odbiegających od formatu przeważającego w danym atrybucie (np "2,54 m (100\")", na "100\"").
        7. Jeśli analizowany parametr odpowiada za niefunkcjonalny rozmiar lub wagę urządzenia (np. "Waga z opakowaniem", "Głębokość z podstawą") pozostaw wartość bez zmian.
           Analogicznie dla parametrów liczbowych typu moc, energia itp. np. średnie zużycie energii nie powinno być mapowane (pozostaw wartość bez zmian).
        8. Jeśli analizowany parametr to funkcyjny wymiar np. "długość przekątnej ekranu" lub  "pojemność powerbanka" należy je zmapować.
        9. Dla kolorów, odcieni i barw: traktuj każdą wartość jako unikalną. Nigdy nie łącz wartości, nawet jeśli są podobne, tłumaczone czy zawierają dodatkowe przymiotniki (np. "Titan Black" ≠ "Black").
        10. Jeśli w wartości parametru pojawią się widoczny błąd np "erfect" lub "podsawowy", zmapuj na wartość bez błędu "perfect" lub "podstawowy".
        11. Nigdy nie łącz różnych przedziałów wartości w jeden klucz, krytycznym błedem jest zrobienie takiego układu: {{"unit": "W", "values": {{"30/1000/1500/2000/2200/2500/3000/3500": ["1000 W", "2500 W", "2000 W", "3500 W", "2200 W", "30/2000/3000W", "25/1000/2000W", "1500 W", "30/2000W"]}}}}
        12. Jeśli wartość zawiera kilka elementów (np. oddzielonych przecinkiem, średnikiem itp.), traktuj ją jako jeden zestaw elementów i reprezentuj w ustalonej kolejności (np. alfabetycznie). W "values" umieść wszystkie oryginalne warianty tego zestawu. Pojedyncze wartości pozostają osobnymi kluczami. Nie dziel elementów na osobne klucze ani nie twórz dodatkowych znormalizowanych wartości.
        13. Parametry opisujące różne poziomy szczegółowości tej samej cechy (np. „typ karty graficznej” i „model karty graficznej”) traktuj jako odrębne, jeśli wartości nie są identyczne.
        14. Parametry opisujące kolory traktuj jako odrębne – nie łącz ich, jeśli wśród wartości znajdują się kreatywne lub marketingowe nazwy kolorów.

        Wynik ma zawierać:
        - wszystkie atrybuty i ich strukturę identyczną jak w danych wejściowych,
        - przy każdej znormalizowanej wartości listę wartości oryginalnych, które zostały zmapowane/usunięte.

        Ważne zasady:
        - Zwróć **wyłącznie JSON**.
        - Nie dodawaj żadnych dodatkowych pól takich jak "length", "items" czy podobnych.
        - Zachowaj dokładnie strukturę sekcji i parametrów z wejściowego JSON-a.
        - Jeśli wartości mają jednostki np. kg, kWh itp. wybierz jedną najbardziej dopasowaną i umieść w kluczu "unit", jeśli brak takiej wartości zostaw unit puste.
        - Jeśli umieszczasz jednostkę w unit to tylko i wyłacznie wtedy możesz usunąć ją z wartości znormalizowanej.
        - Jeśli wartość nie pasuje do żadnej innej, pozostaw ją bez zmian, ale umieść w strukturze znormalizowanych wartości wraz z jej jednostką.
        Format odpowiedzi:
        - Nie używaj zwrotów typu "NIE MAPUJ" czy "ZOSTAW JAK JEST", zamiast tego po prostu umieść oryginalną wartość jako znormalizowaną.

        {{
          "NazwaSekcjiZWejścia": {{
            "NazwaParametruZWejścia": {{
              "znormalizowana_wartość1": {{
                "values":["oryginalna_wartość1",
                "oryginalna_wartość2"],
                "unit": "jednostka"  # jeśli dotyczy
              }}
            }}
          }}
        }}

        Przetwórz następujące dane:
        {json.dumps(block, ensure_ascii=False, indent=2)}
        """
        for _ in range(2):
            llm_maps = ask_gpt_custom(system_prompt, user_prompt)
            print(f'Zapisuję block_mapped_{idx}.json')
            save_json_file(llm_maps, os.path.join(output_dir, f'block_mapped_{idx}_raw.json'))
            try:
                llm_block = json.loads(llm_maps)
                break
            except:
                print(f'Błąd parsowania JSON, ponawiam próbę dla bloku {idx}')

        if "items" in llm_block:
            llm_block= llm_block["items"]

        save_json_file(llm_block, os.path.join(output_dir, f'block_mapped_{idx}.json'))

        for section, params in llm_block.items():
            print(section)
            if section not in llm_map:
                llm_map[section] = {}
            for param, mappings in params.items():
                if param not in llm_map[section]:
                    llm_map[section][param] = {}
                for norm_val, orig_vals in mappings.items():
                    # --- BEZPIECZNE PRZETWARZANIE ORIG_VALS (AI nie zawsze słucha, i daje inny format odpowiedzi) ---
                    # Standardowy przypadek: orig_vals jest słownikiem {"values": [...], "unit": "..."}
                    if isinstance(orig_vals, dict):
                        values = set(orig_vals.get("values", []))
                        unit = orig_vals.get("unit", "")
                    # Niepoprawny przypadek: orig_vals jest stringiem
                    # Zamieniamy go na słownik ze stringiem jako pojedyncza wartość
                    else:
                        values = {orig_vals}
                        unit = ""

                    if norm_val not in llm_map[section][param]:
                        llm_map[section][param][norm_val] = {"values": set(), 'unit': unit}
                    llm_map[section][param][norm_val]["values"].update(values)
    print('C')
    print(llm_map)
    # Konwersja zbiorów na listy przed zapisem
    def convert_sets_to_lists(obj):
        if isinstance(obj, dict):
            return {k: convert_sets_to_lists(v) for k, v in obj.items()}
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, list):
            return [convert_sets_to_lists(i) for i in obj]
        else:
            return obj

    # Przekształć dane przed zapisem
    llm_map_json_safe = convert_sets_to_lists(llm_map)
    save_json_file(llm_map_json_safe, os.path.join(output_dir, 'llm_map.json'))
    print(f"podzielono na {len(blocks)} bloków")

    final_map = {}

    for sekcja, sekcja_data in llm_map.items():
        sekcja_map = {}
        for parametr, parametry in sekcja_data.items():
            param_map = {}
            units = []
            for znormalizowana, oryginalne in parametry.items():
                # jeśli lista zawiera coś więcej niż identyczną wartość
                if any(v != znormalizowana for v in oryginalne['values']):
                    param_map[znormalizowana] = list(oryginalne['values'])
                    units.append(oryginalne.get('unit', ''))
            if param_map:
                # wybierz najczęściej występujący unit
                unit = Counter(units).most_common(1)[0][0] if units else ""
                sekcja_map[parametr] = {
                    "values": param_map,
                    "unit": unit
                }
        if sekcja_map:
            final_map[sekcja] = sekcja_map
    update_form_values_map(record_id, final_map)
    save_json_file(final_map, os.path.join(output_dir, "final_map.json"))

    mapped_values = normalize_values(map_vals, final_map)

    save_json_file(mapped_values, os.path.join(output_dir, 'mapped_values.json'))

    return JSONResponse({
        'success': True,
    })
