import base64
import json
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path
import os
from glob import glob
from collections import defaultdict
from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode

CONNECTION_STR = "Endpoint=sb://sbactuat.servicebus.windows.net/;SharedAccessKeyName=SBActUatPolicy;SharedAccessKey=+yu3D3dQt8fsgI9TSzcC8uxDZpbCRFAmv+ASbBLK2n0="
TOPIC_NAME = "product"
SUBSCRIPTION_NAME = "BazaGrafowa"
SESSION_ID = "0"

DOWNLOAD_FOLDER = Path("database/downloaded_messages")
OLD_FOLDER = Path("database/old_downloaded_messages")
OUTPUT_FOLDER = Path("database/pim_data")
BY_TYPE_FOLDER = Path("database/pim_by_type")

for folder in [DOWNLOAD_FOLDER, OLD_FOLDER, OUTPUT_FOLDER, BY_TYPE_FOLDER]:
    folder.mkdir(exist_ok=True)

BATCH_SIZE = 25
MAX_MESSAGES_PER_RUN = 1000
ROTATE_EVERY = 200
CHECK_INTERVAL = 5 * 60  # 15 minut
PIM_BATCH_SIZE = 1000

kp_categories = [
    'ProductNumber','ProductVersion','Brand','BarcodeCollection','Battery100Wh',
    'BundleType','CNCode','ComponentCollection','Depth','DirectoryGTIN','Height',
    'ImporterGPSR','InstalledBattery','Large','LooseBattery','Name','PIMProductId',
    'Piktograms','PKWiU','ProducerGPSR','ProducerNumber','ProductType',
    'RelatedProductCollection','Weight','Width','CountryOfOrigin',
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
import requests
def json_safe(obj):
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (datetime, timedelta)):
        return str(obj)
    return obj
def send_to_pim_endpoint(new_messages):
    url = "http://0.0.0.0:7001/pim"
    for obj in new_messages:
        body = json.loads(obj['body'])
        try:
            resp = requests.post(url, json=body, timeout=10)
            if resp.status_code == 200:
                print(f"[info] wysłano {body.get('PIMProductId', 'UNKNOWN')}")
            else:
                print(f"[warn] błąd wysyłki {body.get('PIMProductId', 'UNKNOWN')}: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"[error] problem z wysyłką {body.get('PIMProductId', 'UNKNOWN')}: {e}")
def message_body_to_str_or_b64(msg):
    try:
        body_parts = list(msg.body)
    except Exception:
        return None
    raw = b"".join(part if isinstance(part, (bytes, bytearray)) else str(part).encode() for part in body_parts)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(raw).decode("ascii")}

def safe_dict(d):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(k, bytes):
            try:
                k = k.decode("utf-8")
            except Exception:
                k = repr(k)
        out[k] = v
    return out

def message_to_dict(msg):
    body = message_body_to_str_or_b64(msg)
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except Exception:
            body = {"base64": base64.b64encode(body).decode("ascii")}
    props = {
        "message_id": getattr(msg, "message_id", None),
        "session_id": getattr(msg, "session_id", None),
        "content_type": getattr(msg, "content_type", None),
        "correlation_id": getattr(msg, "correlation_id", None),
        "subject": getattr(msg, "subject", None),
        "application_properties": safe_dict(getattr(msg, "application_properties", {})),
        "enqueued_time_utc": getattr(msg, "enqueued_time_utc", None),
        "sequence_number": getattr(msg, "sequence_number", None),
    }
    return {"body": body, "properties": props}

def new_outfile_path(counter: int, prefix="sb") -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    #ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return DOWNLOAD_FOLDER / f"{prefix}__{TOPIC_NAME}__{SUBSCRIPTION_NAME}__session_{SESSION_ID}__part{counter}_{ts}.jsonl"

def process_pim_files():
    all_files = glob(str(DOWNLOAD_FOLDER / "*.jsonl"))
    pim_list = []
    file_count = 0

    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                obj_body = json.loads(obj['body'])
                filtered_obj = {k: v for k, v in obj_body.items() if k in kp_categories or k in pim_categories}
                obj['body'] = filtered_obj
                pim_list.append(obj)

                if len(pim_list) >= PIM_BATCH_SIZE:
                    output_path = OUTPUT_FOLDER / f"pim_{file_count}.json"
                    with open(output_path, "w", encoding="utf-8") as f_out:
                        json.dump({"pim": pim_list}, f_out, ensure_ascii=False, indent=2)
                    print(f"[info] zapisano {len(pim_list)} elementów do {output_path}")
                    pim_list = []
                    file_count += 1

        old_path = OLD_FOLDER / Path(file_path).name
        os.rename(file_path, old_path)
        print(f"[info] przeniesiono {file_path} -> {old_path}")

    if pim_list:
        output_path = OUTPUT_FOLDER / f"pim_{file_count}.json"
        with open(output_path, "w", encoding="utf-8") as f_out:
            json.dump({"pim": pim_list}, f_out, ensure_ascii=False, indent=2)
        print(f"[info] zapisano pozostałe {len(pim_list)} elementów do {output_path}")
def process_new_messages_by_type(new_messages):
    """
    new_messages: lista słowników {"body": {...}, "properties": {...}}
    Zapisuje każdy rekord w formacie JSONL, aby uniknąć dużych plików i błędów JSONDecodeError.
    """
    for obj in new_messages:
        # filtrujemy tylko potrzebne pola
        try:
            obj_body = json.loads(obj['body'])
        except (TypeError, json.JSONDecodeError):
            # jeśli body jest dict już, zostawiamy
            obj_body = obj['body'] if isinstance(obj['body'], dict) else {}
        filtered_obj = {k: v for k, v in obj_body.items() if k in kp_categories or k in pim_categories}
        obj['body'] = filtered_obj

        product_type = filtered_obj.get("ProductType", "UNKNOWN")
        safe_type = "".join(c if c.isalnum() else "_" for c in str(product_type))
        output_path = BY_TYPE_FOLDER / f"{safe_type}.jsonl"

        # jeśli plik istnieje, dopisujemy w trybie "a", jeśli nie - tworzymy
        with open(output_path, "a", encoding="utf-8") as f_out:
            json.dump(obj, f_out, ensure_ascii=False, default=json_safe)
            f_out.write("\n")


def process_by_type():
    all_files = glob(str(OUTPUT_FOLDER / "pim_*.json"))
    grouped = defaultdict(list)

    for file_path in all_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for obj in data.get("pim", []):
                product_type = obj.get("body", {}).get("ProductType", "UNKNOWN")
                grouped[product_type].append(obj)

    for product_type, items in grouped.items():
        safe_type = "".join(c if c.isalnum() else "_" for c in str(product_type))
        output_path = BY_TYPE_FOLDER / f"{safe_type}.json"

        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f_in:
                existing_items = json.load(f_in).get("pim", [])
        else:
            existing_items = []

        all_items = existing_items + items

        with open(output_path, "w", encoding="utf-8") as f_out:
            json.dump({"pim": all_items}, f_out, ensure_ascii=False, indent=2, default=json_safe)

        print(f"[info] zapisano {len(items)} nowych elementów dla ProductType={product_type} -> {output_path} (total {len(all_items)})")

def fetch_and_process():
    total = 0
    current_count = 0
    file_counter = 1
    fetched_messages = []  # <-- tu trzymamy wszystkie pobrane rekordy
    fh = new_outfile_path(file_counter).open("a", encoding="utf-8")

    with ServiceBusClient.from_connection_string(CONNECTION_STR) as client:
        with client.get_subscription_receiver(
            topic_name=TOPIC_NAME,
            subscription_name=SUBSCRIPTION_NAME,
            session_id=SESSION_ID,
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            max_lock_renewal_duration=timedelta(minutes=5)
        ) as receiver:

            while total < MAX_MESSAGES_PER_RUN:
                msgs = receiver.receive_messages(max_message_count=BATCH_SIZE, max_wait_time=5)
                if not msgs:
                    break

                for msg in msgs:
                    try:
                        record = message_to_dict(msg)
                        fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
                        fetched_messages.append(record)  # <-- dodajemy do listy
                        current_count += 1
                        total += 1
                        fh.flush()
                        receiver.complete_message(msg)

                        if current_count >= ROTATE_EVERY:
                            fh.close()
                            file_counter += 1
                            current_count = 0
                            fh = new_outfile_path(file_counter).open("a", encoding="utf-8")

                        if total >= MAX_MESSAGES_PER_RUN:
                            break

                    except Exception as e:
                        print("[error] problem z wiadomością:", e)
                        receiver.abandon_message(msg)

    fh.close()
    print(f"[info] pobrano i zapisano {total} wiadomości z Service Bus")

    # od razu przetwarzamy i filtrujemy do PIM po ProductType
    process_new_messages_by_type(fetched_messages)
    # send_to_pim_endpoint(fetched_messages)



if __name__ == "__main__":
    while True:
        print(f"[info] start fetchu o {datetime.now(UTC).isoformat()}")
        fetch_and_process()
        print(f"[info] koniec fetchu, czekam {CHECK_INTERVAL/60:.0f} minut...")
        time.sleep(CHECK_INTERVAL)
