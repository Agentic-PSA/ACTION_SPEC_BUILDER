# src/services/ean_service.py
import json
import aiohttp
import asyncio
import base64
import requests
from functools import lru_cache


@lru_cache(maxsize=100)
def get_token(username="admin", password="admin"):
    url = "http://172.16.10.3:31008/openid/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': 'Basic ' + base64.b64encode(b'spiffworkflow-backend:my_open_id_secret_key').decode('utf-8')
    }
    data = {
        'grant_type': 'password',
        'code': 'admin:this_is_not_secure_do_not_use_in_production',
        'username': username,
        'password': password,
        'client_id': 'spiffworkflow-backend'
    }

    response = requests.post(url, headers=headers, data=data)
    return response.json().get("access_token")


async def read_eans(data):
    with open('data/ean_dict.json', 'r', encoding='utf-8') as f:
        ean_dict = json.load(f)
    return {k: ean for k, ean in ean_dict.items() if ean['type'] in data}

async def read_eans_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        ean_dict = json.load(f)
    return ean_dict

async def send_message(session, message, data):
    headers = {
        'Authorization': f'Bearer {get_token()}',
        'Content-Type': 'application/json'
    }

    try:
        async with session.post(f'http://172.16.10.3:31008/v1.0/messages/{message}',
                               headers=headers, json=data, timeout=30) as response:
            response_data = await response.json()
            if "error_code" in response_data:
                return None
            return response_data['task_data']
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def is_ean_valid(ean):
    if not ean or not isinstance(ean, str):
        print("is_ean_valid 1")
        return False

    # # Szybkie sprawdzenie podstawowych warunków
    # if len(ean) < 8 or len(ean) > 13 or not ean.isdigit():
    #     print("is_ean_valid 1")
    #     return False

    # # EAN-13 lub EAN-8 check
    # digits = [int(d) for d in ean]
    # checksum = sum(digits[-2::-2]) + sum(d * 3 for d in digits[-3::-2])
    # print("is_ean_valid 1")
    # return (10 - (checksum % 10)) % 10 == digits[-1]
    if len(ean) < 8 or len(ean) > 13 or not ean.isdigit():
        return False
 
    # Dodaj zera na początku, aby uzyskać długość 13 cyfr
    ean = ean.zfill(13)
 
    sum_even = sum(int(ean[i]) for i in range(0, 12, 2))
    sum_odd = sum(int(ean[i]) for i in range(1, 12, 2))
    total_sum = sum_even + sum_odd * 3
 
    # Oblicz cyfrę kontrolną
    check_digit = (10 - (total_sum % 10)) % 10
 
    return check_digit == int(ean[-1])

def generate_ean_variants(ean):
    # Bardziej zwięzła implementacja
    variants = [ean]

    if 8 <= len(ean) <= 13:
        if len(ean) < 13:
            variants.append(ean.zfill(13))
        if len(ean) == 13 and ean.startswith('0'):
            variants.append(ean[1:])
        if len(ean) == 13 and ean.startswith('00'):
            variants.append(ean[2:])

    return list(set(variants))  # Usuwamy duplikaty