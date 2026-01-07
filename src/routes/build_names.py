from starlette.responses import JSONResponse
from src.services.ai_service import ai_build_names, ai_build_suppliers
import csv
import json
from collections import defaultdict
import re


async def build_suppliers(request):

    z = 0  # od którego wiersza zaczynamy (0-based)
    x = 1000000  # ile linii chcesz wczytać
    y = 10   # rozmiar paczki
    input_rows = []

    # konwertowanie pliku wejsciowego - krok 1
    # with open("data/dostawcy.csv", "r", encoding="cp1250") as fin, \
    #     open("data/dostawcy_ok.csv", "w", encoding="utf-8", newline="") as fout:
        
    #     for line in fin:
    #         if not line.startswith('2'):
    #             line = line.rstrip("\r\n") + '"' + "\n"
    #         else:
    #             line = line.rstrip("\r\n") + "\n"
    #         fout.write(line)
    # exit()

    # konwertowanie pliku wejsciowego - krok 2
    # with open("data/dostawcy.csv", "r", encoding="utf-8", errors="replace") as fin, \
    #     open("data/dostawcy_ok3.csv", "w", encoding="utf-8", newline="") as fout:
        
    #     for line in fin:
    #         line = line.rstrip("\n")
    #         if line.endswith('&lt'):
    #             line = line + '"'
    #         line = line + "\n"
    #         fout.write(line)
    # exit()

    VALID_ID_REGEX = re.compile(r"\b\d{5}(?:ADR|EUR|USD)?\b")

    def row_has_valid_id(row_dict):
        """Zwraca True jeśli wiersz zawiera przynajmniej jedno prawidłowe ID"""
        for value in row_dict.values():
            if not value:
                continue
            # szukamy wszystkich dopasowań regexem
            if VALID_ID_REGEX.search(value):
                return True  # ✔ wiersz ma prawidłowe ID
        return False  # ❌ brak ID → wiersz odrzucony

    with open("data/dostawcy_ok3.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)  # pierwsza linia
        header[0] = header[0].lstrip("\ufeff")
        # print("HEADER:", header)
        for i, row in enumerate(reader):
            if i < z:
                continue  # pomijamy wiersze przed z
            if i >= z + x:
                break
            row_dict = dict(zip(header, row))
            if not row_has_valid_id(row_dict):
                # print('BAD')
                continue  
            # print("----")
            # print(json.dumps(row_dict, ensure_ascii=False, indent=2))
            # print('OK')
            input_rows.append(row_dict)

    batches = [input_rows[i:i + y] for i in range(0, len(input_rows), y)]
    # print(len(input_rows))
    # print(len(batches))
    # exit()

    # Zapis i przetwarzanie paczek
    output_file = "aaa3_supliers_ok3.txt"
    output = []
    try:
        with open(output_file, "a", encoding="utf-8") as fw:
            for batch_index, batch in enumerate(batches, start=1):
                print(f"Przetwarzam paczkę {batch_index} - {len(batch)} wierszy")
                # with open(f"aaa_batch_in_{batch_index}.json", "w", encoding="utf-8") as ft1:
                #     json.dump(batch, ft1, ensure_ascii=False, indent=2)
                try:
                    batch_output = ai_build_suppliers(batch)  # przetwarzanie paczki
                    # normalizacja
                    if batch_output is None:
                        batch_output = []
                    elif isinstance(batch_output, dict) or isinstance(batch_output, str):
                        batch_output = [batch_output]
                    elif not isinstance(batch_output, list):
                        batch_output = [batch_output]

                    # zapis batch_output
                    for item in batch_output:
                        try:
                            # jeśli AI zwróci dict z polami id, name, email
                            if isinstance(item, dict):
                                line = f"{item.get('id','')};{item.get('name','')};{item.get('email','')}"
                            else:
                                # jeśli AI zwróci string lub coś dziwnego – zapis jako string
                                line = str(item)
                            fw.write(line + "\n")
                            output.append(line)
                        except Exception:
                            # absolutnie nic nie powinno przerwać zapis
                            fw.write(str(item) + "\n")
                            output.append(str(item))
                    fw.flush()

                except Exception as e:
                    print(f"Batch {batch_index} FAILED: {e}")

                    # zapisz problematyczny batch do debug
                    with open(f"aaa_batch_failed_in_{batch_index}.json", "w", encoding="utf-8") as f:
                        json.dump(batch, f, ensure_ascii=False, indent=2)
                    # próbujemy też zapisać batch_output w bezpieczny sposób
                    try:
                        with open(f"aaa_batch_failed_ou_{batch_index}.json", "w", encoding="utf-8") as f:
                            json.dump(batch_output, f, ensure_ascii=False, indent=2)
                    except Exception:
                        # jeśli json.dump nie działa, zapisujemy jako string
                        with open(f"aaa_batch_failed_ou_{batch_index}.txt", "w", encoding="utf-8") as f:
                            f.write(str(batch_output))

                    continue
    except KeyboardInterrupt:
        print("\nCtrl+C wykryte – przerywam proces")
        # opcjonalnie zapis ostatniego batch lub output
        exit()

    return JSONResponse({
        "success": True,
        "count": len(output)
    })



async def build_names(request):
    z = 1000  # od którego wiersza zaczynamy (0-based)
    x = 9000  # ile linii chcesz wczytać
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
            # with open(f"aaa_batch_in_{batch_index}.json", "w", encoding="utf-8") as ft1:
            #     json.dump(batch, ft1, ensure_ascii=False, indent=2)
            batch_output = ai_build_names(batch)  # przetwarzanie paczki
            for item in batch_output:
                fw.write(json.dumps(item, ensure_ascii=False) + "\n")
            fw.flush()  # wymusza zapis do pliku od razu
            # with open(f"aaa_batch_ou_{batch_index}.json", "w", encoding="utf-8") as ft2:
            #     json.dump(batch_output, ft2, ensure_ascii=False, indent=2)
            output.extend(batch_output)

    # with open(f"aaa3_names.json", "w", encoding="utf-8") as f:
    #     json.dump(output, f, ensure_ascii=False, indent=2)


    return JSONResponse({
        "success": True,
        "count": len(output)
    })

