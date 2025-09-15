# src/services/file_service.py
import os
import json


def save_json_file(data, filename):
    """
    Zapisuje dane w formacie JSON do pliku.

    Args:
        data: Dane do zapisania
        filename: Nazwa pliku
    """
    os.makedirs('output', exist_ok=True)
    with open(f'{filename}', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)