import pandas as pd
import json

# wczytaj plik XLSX
df = pd.read_excel("data/drzewo z produktami.xlsx")

# otwórz plik do zapisu w formacie jsonl
with open("output.jsonl", "w", encoding="utf-8") as f:
    for _, row in df.iterrows():
        record = {
            "messages": [
                {
                    "role": "system",
                    "content": "Jesteś chatbotem, który pomaga przypisywać kategorie do produktów."
                },
                {
                    "role": "user",
                    "content": f"Jaka jest kategoria dla {row['Value']}"
                },
                {
                    "role": "assistant",
                    "content": f"{row['CategoryName_Level2']} - {row['CategoryName_Level3']} - {row['SalesChannelName']}"
                }
            ]
        }
        # zapis jednej linii w pliku JSONL
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
