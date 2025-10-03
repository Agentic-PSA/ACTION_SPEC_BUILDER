import json
import os
from glob import glob

kp_categories = [
    'ProductNumber','ProductVersion','Brand','BarcodeCollection','Battery100Wh',
    'BundleType','CNCode','ComponentCollection','Depth','DirectoryGTIN','Height',
    'ImporterGPSR','InstalledBattery','Large','LooseBattery','Name','PIMProductId',
    'Piktograms','PKWiU','ProducerGPSR','ProducerNumber','ProductType',
    'RelatedProductCollection','SferisName','Weight','Width','CountryOfOrigin',
    'CategoryMapCollection'
]

pim_categories = [
    'PIMProductId','Brand','CategoryMapCollection','ProductType','NameEN','NameDE',
    'TranslationCollection','SferisName','CNCode','PKWiU','Intrastatname',
    'IntrastatnameLong','CountryOfOrigin','Weight','Height','Width','Depth',
    'ProducerGPSR','ImporterGPSR','Piktograms','EnergyLabel','Battery100Wh',
    'InstalledBattery','LooseBattery','Large','ComponentCollection',
    'RelatedProductCollection','Speccollection','Photocollection'
]

def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

if __name__ == "__main__":
    input_folder = "downloaded_messages"
    old_folder = "old_downloaded_messages"
    output_folder = "pim_data"

    ensure_dir(output_folder)
    ensure_dir(old_folder)

    all_files = glob(os.path.join(input_folder, "*.jsonl"))
    pim_list = []
    file_count = 0

    for file_path in all_files:
        for obj in read_jsonl(file_path):
            obj_body = json.loads(obj['body'])
            filtered_obj = {k: v for k, v in obj_body.items() if k in kp_categories or k in pim_categories}
            obj['body'] = filtered_obj
            pim_list.append(obj)

            if len(pim_list) >= 1000:
                output_path = os.path.join(output_folder, f"pim_{file_count}.json")
                print(f"Writing {len(pim_list)} items to {output_path}")
                with open(output_path, "w", encoding="utf-8") as f_out:
                    json.dump({"pim": pim_list}, f_out, ensure_ascii=False, indent=2)
                pim_list = []
                file_count += 1

        # po przetworzeniu całego pliku przenieś go do old_downloaded_messages
        base_name = os.path.basename(file_path)
        old_path = os.path.join(old_folder, base_name)
        os.rename(file_path, old_path)
        print(f"Moved {file_path} -> {old_path}")

    # zapis pozostałych elementów jeśli jest ich mniej niż 1000
    if pim_list:
        output_path = os.path.join(output_folder, f"pim_{file_count}.json")
        with open(output_path, "w", encoding="utf-8") as f_out:
            json.dump({"pim": pim_list}, f_out, ensure_ascii=False, indent=2)
