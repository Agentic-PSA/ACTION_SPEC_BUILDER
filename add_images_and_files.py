from neo4j import GraphDatabase
import requests
import os
from dotenv import load_dotenv
load_dotenv()
import json
import aiohttp
import asyncio
import base64
import requests
from functools import lru_cache
import time
import hashlib


# konfiguracja
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_URI = f'bolt://{os.environ.get("NEO4J_HOST")}:{os.environ.get("NEO4J_PORT")}'

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_products(tx):
    query = """
    MATCH (p:Product)
    WHERE p.Photocollection IS NULL
    RETURN p.action AS productId
    """
    result = tx.run(query)
    return [record["productId"] for record in result]


def update_images_and_files(tx, product_id, images, files):
    query = """
    MATCH (p:Product {action: $product_id})
    SET p.Photocollection = $images, p.FileCollection = $files
    """
    tx.run(query, product_id=product_id, images=images, files=files)

async def fetch_product_from_api(action: str):
    user = "BLUEBOX"
    key = os.environ.get("BLUEBOX_KEY")

    current_time = int(time.time())
    data = {
        "user": user,
        "key": hashlib.md5((key + str(current_time)).encode()).hexdigest(),
        "time": current_time,
        "requestType": "GetProduct",
        "dax_index": action
    }
    url = "https://icecat.action.pl/api/GetProduct"
    headers = {'Content-Type': 'application/json'}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data, ssl=False) as response:
            try:
                panel_response = json.loads(await response.text())
                panel_data = panel_response.get("product", {})
            except Exception as e:
                print(f"Error parsing JSON response: {e}")
                panel_data = {}
    return panel_data

async def main():
    with driver.session() as session:

        product_ids = session.execute_read(get_products)
        # product_ids = ['AGDDLOEXP0301']
        # print(product_ids)

        for product_id in product_ids:
            print(f"Przetwarzam {product_id}")
            product = await fetch_product_from_api(product_id) 
            images = product.get('images',[])
            parsed_images = [{'Photolink': image.get('url', '')} for image in images]
            files = product.get('multimedia',{}).get('PL',[])
            parsed_files = [{'Filelink': f.get('url', ''), 'Name': f.get('description','')} for f in files]
            session.execute_write(update_images_and_files, product_id, json.dumps(parsed_images), json.dumps(parsed_files))

    driver.close()


if __name__ == "__main__":
    asyncio.run(main())
