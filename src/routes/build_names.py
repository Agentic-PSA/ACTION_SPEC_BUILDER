from starlette.responses import JSONResponse
from src.services.ai_service import ai_build_names
import csv
import json
from collections import defaultdict


async def build_names(request):
    z = 0  # od którego wiersza zaczynamy (0-based)
    x = 1000  # ile linii chcesz wczytać
    y = 50   # rozmiar paczki
    input_rows = []

    with open("data/nazwy_csv.csv", newline="", encoding="cp1250") as f:
        reader = csv.reader(f)
        header = next(reader)  # pierwsza linia
        # print("HEADER:", header)
        for i, row in enumerate(reader):
            if i < z:
                continue  # pomijamy wiersze przed z
            if i >= z + x:
                break
            input_rows.append(row)

    # Grupowanie po product_number
    grouped = defaultdict(list)
    for row in input_rows:
        product_number = row[0]
        grouped[product_number].append(row)

    # Tworzenie listy grup
    grouped_rows = list(grouped.values())

    # Tworzenie paczek z zachowaniem grup
    batches = []
    current_batch = []
    for group in grouped_rows:
        if current_batch and len(current_batch) + len(group) > y:
            batches.append(current_batch)
            current_batch = []
        current_batch.extend(group)
    if current_batch:
        batches.append(current_batch)

    # Zapis i przetwarzanie paczek
    output_file = "aaa3_names.jsonl"
    output = []
    with open(output_file, "a", encoding="utf-8") as fw:
        for batch_index, batch in enumerate(batches, start=1):
            print(f"Przetwarzam paczkę {batch_index} - {len(batch)} wierszy")
            with open(f"aaa_batch_in_{batch_index}.json", "w", encoding="utf-8") as ft1:
                json.dump(batch, ft1, ensure_ascii=False, indent=2)
            batch_output = ai_build_names(batch)  # przetwarzanie paczki
            for item in batch_output:
                fw.write(json.dumps(item, ensure_ascii=False) + "\n")
            fw.flush()  # wymusza zapis do pliku od razu
            with open(f"aaa_batch_ou_{batch_index}.json", "w", encoding="utf-8") as ft2:
                json.dump(batch_output, ft2, ensure_ascii=False, indent=2)
            output.extend(batch_output)

    with open(f"aaa3_names.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


    return JSONResponse({
        "success": True,
        "count": len(output)
    })

