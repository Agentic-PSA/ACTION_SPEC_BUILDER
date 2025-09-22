import datetime
import json
import os

import polars as pl
from starlette.responses import JSONResponse

from src.services.ai_service import ask_gpt_custom, ask_sonoma_custom
from src.services.file_service import save_json_file

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

def normalize_values(original_map, llm_map):
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
            # build lookup orig -> norm
            orig_to_norm = {}
            if section in llm_map and param in llm_map[section]:
                for norm_val, orig_vals in llm_map[section][param].items():
                    # orig_vals może być set/list — iterujemy po nim
                    for ov in orig_vals:
                        # pomijamy mapowania typu "X": ["X"]
                        if ov != norm_val:
                            orig_to_norm[ov] = norm_val
            # teraz zamieniamy wartości, zachowując kolejność i unikając duplikatów
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
    output_dir = create_output_directory()

    def save_to_output_dir(data, filename):
        file_path = os.path.join(output_dir, filename)
        save_json_file(data, file_path)
        return file_path


    with open('data/all_params_after_449_small.json', 'r', encoding='utf-8') as file:
        map_vals = json.load(file)
    MAX_LENGTH = 40
    blocks = [{'length': 0, 'items': {}}]
    llm_map = {}
    for map in map_vals.items():
        for k,v  in map[1].items():
            if len(v)<2:
                if map[0] not in llm_map:
                    llm_map[map[0]] = {}
                llm_map[map[0]][k] = {_v: [_v] for _v in v}
                continue
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
        1. Przeczytaniu całej formatki w JSON (atrybuty i ich wypełnienia).
        2. Usunięciu duplikatów w wartościach atrybutów.
        3. Jeśli wartości różnią się tylko formatem (np. cal/cm, zapis liczbowy z przecinkiem/kropką, nawiasy) → ujednolić do jednego formatu.
        4. Jeśli wartości są bardzo zbliżone (np. wynik konwersji jednostek, różnice z zaokrągleń) → potraktować jako duplikaty i zostawić tylko jedną reprezentatywną wartość.
        5. Pojedynczy format wartości nie może być wartością znormalizowaną, błędem jest przypisanie wartości (200 kWh, 300 kWh, 400 kWh) do znormalizowanej wartości (kWh).
        6. Jeśli liczbowe wartości różnią się wartością po przecinku i jest to znikoma roznica (mniej niż 1% wartości) → potraktować jako duplikaty i zostawić tylko jedną reprezentatywną wartość.
        7. Utworzeniu wspólnych wartości dla kilku nazw oznaczających to samo (np. „Direct-LED BLU” = „Direct-LED”, lub ""4K Ultra HD" = "Ultra HD").
        8. Poprawieniu wszystkich wartości odbiegających od formatu przeważającego w danym atrybucie (np "2,54 m (100\")", na "100\"").

        Wynik ma zawierać:
        - wszystkie atrybuty i ich strukturę identyczną jak w danych wejściowych,
        - przy każdej znormalizowanej wartości listę wartości oryginalnych, które zostały zmapowane/usunięte.

        Ważne zasady:
        - Zwróć **wyłącznie JSON**.
        - Nie dodawaj żadnych dodatkowych pól takich jak "length", "items" czy podobnych.
        - Zachowaj dokładnie strukturę sekcji i parametrów z wejściowego JSON-a.
        - Wartości w `"znormalizowana_wartość"` umieszczaj tylko dla faktycznie zmapowanych/usuniętych wartości.

        Format odpowiedzi:

        {{
          "NazwaSekcjiZWejścia": {{
            "NazwaParametruZWejścia": {{
              "znormalizowana_wartość": [
                "oryginalna_wartość1",
                "oryginalna_wartość2"
              ]
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
            if section not in llm_map:
                llm_map[section] = {}
            for param, mappings in params.items():
                if param not in llm_map[section]:
                    llm_map[section][param] = {}
                for norm_val, orig_vals in mappings.items():
                    if norm_val not in llm_map[section][param]:
                        llm_map[section][param][norm_val] = set()
                    llm_map[section][param][norm_val].update(orig_vals)

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
            for znormalizowana, oryginalne in parametry.items():
                # jeśli lista zawiera coś więcej niż identyczną wartość
                if any(v != znormalizowana for v in oryginalne):
                    param_map[znormalizowana] = list(oryginalne)
            if param_map:
                sekcja_map[parametr] = param_map
        if sekcja_map:
            final_map[sekcja] = sekcja_map

    save_json_file(final_map, os.path.join(output_dir, "final_map.json"))

    mapped_values = normalize_values(map_vals, final_map)

    save_json_file(mapped_values, os.path.join(output_dir, 'mapped_values.json'))

    return JSONResponse({
        'success': True,
    })