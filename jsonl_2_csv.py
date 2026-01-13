import json
import csv

# Ścieżki do plików
input_file = "aaa_names_all.jsonl"
output_file = "aaa_names_all.csv"

# Otwieramy plik JSONL i wczytujemy wszystkie wiersze jako słowniki
data = []
with open(input_file, "r", encoding="utf-8") as f:
    for line in f:
        data.append(json.loads(line))

# Jeśli plik nie jest pusty, zapisujemy do CSV
if data:
    # Pobieramy nagłówki (klucze) z pierwszego obiektu JSON
    headers = data[0].keys()
    
    # Tworzymy plik CSV
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)

print(f"Plik {output_file} został utworzony.")
