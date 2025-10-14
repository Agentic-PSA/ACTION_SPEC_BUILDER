import json
import os

from starlette.responses import JSONResponse
from src.services.file_service import save_json_file
from src.routes.map_values import create_output_directory, normalize_values


async def generate_mapped_values():
    output_dir = "output3/2025-09-24_08-49-26"

    # Wczytanie danych wejściowych
    with open('data/all_params_after_449.json', 'r', encoding='utf-8') as f:
        map_vals = json.load(f)

    # Wczytanie gotowego final_map.json
    final_map_path = os.path.join(output_dir, "final_map.json")
    if not os.path.exists(final_map_path):
        raise FileNotFoundError(f"Brak pliku {final_map_path}, uruchom najpierw skrypt budujący final_map.json")

    with open(final_map_path, "r", encoding="utf-8") as f:
        final_map = json.load(f)

    # Normalizacja
    mapped_values = normalize_values(map_vals, final_map)

    # Zapis wyników
    save_json_file(mapped_values, os.path.join(output_dir, 'mapped_values.json'))

    return JSONResponse({'success': True})


if __name__ == "__main__":
    import asyncio
    asyncio.run(generate_mapped_values())
