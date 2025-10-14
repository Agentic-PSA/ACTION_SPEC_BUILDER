import json
import os
from glob import glob
from collections import defaultdict

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

if __name__ == "__main__":
    input_folder = "pim_data"
    output_folder = "pim_by_type"

    ensure_dir(output_folder)

    all_files = glob(os.path.join(input_folder, "pim_*.json"))
    grouped = defaultdict(list)
    total_count = 0  # licznik wszystkich przetworzonych obiektów

    # czytamy wszystkie pliki pim_x.json
    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for obj in data.get("pim", []):
                product_type = obj.get("body", {}).get("ProductType", "UNKNOWN")
                grouped[product_type].append(obj)
                total_count += 1

                # co 5000 obiektów wypisz stan grup
                if total_count % 5000 == 0:
                    print(f"\n--- Processed {total_count} objects ---")

    # zapisujemy dane do nowych plików
    for product_type, items in grouped.items():
        # zamiana spacji i znaków specjalnych żeby nazwa pliku była bezpieczna
        safe_type = "".join(c if c.isalnum() else "_" for c in str(product_type))
        output_path = os.path.join(output_folder, f"{safe_type}.json")

        print(f"Writing {len(items)} items for ProductType={product_type} -> {output_path}")
        with open(output_path, "w", encoding="utf-8") as f_out:
            json.dump({"pim": items}, f_out, ensure_ascii=False, indent=2)
