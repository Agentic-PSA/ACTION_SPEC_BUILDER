import base64
import json
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from azure.servicebus import ServiceBusClient, ServiceBusReceiveMode

CONNECTION_STR = "Endpoint=sb://sbactuat.servicebus.windows.net/;SharedAccessKeyName=SBActUatPolicy;SharedAccessKey=+yu3D3dQt8fsgI9TSzcC8uxDZpbCRFAmv+ASbBLK2n0="

TOPIC_NAME = "product"
SUBSCRIPTION_NAME = "BazaGrafowa"
SESSION_ID = "0"

OUT_DIR = Path("downloaded_messages")
OUT_DIR.mkdir(exist_ok=True)

BATCH_SIZE = 25
MAX_EMPTY_RECEIVES = 3
ROTATE_EVERY = 200


def message_body_to_str_or_b64(msg):
    try:
        body_parts = list(msg.body)
    except Exception:
        return None

    raw = b"".join(
        part if isinstance(part, (bytes, bytearray)) else str(part).encode()
        for part in body_parts
    )
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


def new_outfile_path(counter: int) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return OUT_DIR / f"{TOPIC_NAME}__{SUBSCRIPTION_NAME}__session_{SESSION_ID}__part{counter}_{ts}.jsonl"


def drain_and_save():
    total = 0
    empty_rounds = 0
    file_counter = 1
    current_count = 0
    fh = new_outfile_path(file_counter).open("w", encoding="utf-8")

    with ServiceBusClient.from_connection_string(CONNECTION_STR) as client:
        with client.get_subscription_receiver(
                topic_name=TOPIC_NAME,
                subscription_name=SUBSCRIPTION_NAME,
                session_id=SESSION_ID,
                receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                max_lock_renewal_duration=timedelta(minutes=30)
        ) as receiver:

            while True:
                msgs = receiver.receive_messages(
                    max_message_count=BATCH_SIZE, max_wait_time=5
                )
                if not msgs:
                    empty_rounds += 1
                    print(f"[info] pusty fetch #{empty_rounds}")
                    if empty_rounds >= MAX_EMPTY_RECEIVES:
                        print("[info] brak nowych wiadomości — kończę.")
                        break
                    else:
                        continue
                empty_rounds = 0

                for msg in msgs:
                    try:
                        record = message_to_dict(msg)
                        fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
                        current_count += 1
                        total += 1
                        fh.flush()  # żeby nie utknęło w buforze
                        receiver.complete_message(msg)  # usuwamy tylko, jeśli zapis się udał

                        if current_count >= ROTATE_EVERY:
                            fh.close()
                            file_counter += 1
                            current_count = 0
                            fh = new_outfile_path(file_counter).open("w", encoding="utf-8")

                    except Exception as e:
                        print("[error] problem z wiadomością:", e)
                        receiver.abandon_message(msg)  # zwracamy do kolejki

                fh.flush()
                print(f"[info] batch {len(msgs)} — łącznie: {total}")

    fh.close()
    print(f"Zakończono. Pobrano i zapisano: {total} wiadomości")


if __name__ == "__main__":
    drain_and_save()
