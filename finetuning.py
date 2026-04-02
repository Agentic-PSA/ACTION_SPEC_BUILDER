import csv
import json

input_file = "input.csv"
output_file = "output.jsonl"

with open(input_file, mode="r", encoding="cp1250") as csv_file, \
     open(output_file, mode="w", encoding="utf-8") as jsonl_file:
    
    reader = csv.DictReader(csv_file)
    
    for row in reader:
        nazwa = row["Nazwa produktu"]
        cn = row["Kod CN"]
        pkwiu = row["PKWiU"]

        record = {
            "messages": [
                {
                    "role": "system",
                    "content": "Jesteś ekspertem ds. klasyfikacji towarów. Twoim zadaniem jest przypisywanie odpowiedniego kodu CN oraz numeru PKWiU na podstawie podanej nazwy produktu."
                },
                {
                    "role": "user",
                    "content": f"Podaj kody dla: {nazwa}"
                },
                {
                    "role": "assistant",
                    "content": f"Kod CN: {cn} | PKWiU: {pkwiu}"
                }
            ]
        }

        # --- ZAPIS DO JSONL ---
        json_line = json.dumps(record, ensure_ascii=False)
        jsonl_file.write(json_line + "\n")

print("Zapisano do JSONL!")