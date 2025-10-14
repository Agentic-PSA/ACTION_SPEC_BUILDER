import json
import os

from starlette.responses import JSONResponse
from src.services.file_service import save_json_file
from src.routes.map_values import create_output_directory, normalize_values  # zakładam że Twój plik główny to main.py


async def test_map_values():
    output_dir = create_output_directory()

    def load_block_file(idx):
        file_path = os.path.join("output3", "2025-09-23_08-09-23", f"block_mapped_{idx}.json")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def convert_sets_to_lists(obj):
        if isinstance(obj, dict):
            return {k: convert_sets_to_lists(v) for k, v in obj.items()}
        elif isinstance(obj, set):
            return list(obj)
        elif isinstance(obj, list):
            return [convert_sets_to_lists(i) for i in obj]
        else:
            return obj

    with open('data/all_params_after_449.json', 'r', encoding='utf-8') as file:
        map_vals = json.load(file)

    llm_map = {}
    idx = 0
    while True:
        file_path = os.path.join("output3", "2025-09-23_08-09-23", f"block_mapped_{idx}.json")
        if not os.path.exists(file_path):
            break
        print(f"Wczytuję {file_path}")
        llm_block = load_block_file(idx)

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
        idx += 1

    llm_map_json_safe = convert_sets_to_lists(llm_map)
    save_json_file(llm_map_json_safe, os.path.join(output_dir, 'llm_map.json'))

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

    return JSONResponse({'success': True})


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_map_values())
