from src.routes.group_types import create_updated_csv
import json


if __name__ == "__main__":
    with open('output2/2025-09-17_16-03-36/current_merged.json', 'r' , encoding='utf-8') as file:
        current_merged = json.load(file)
    create_updated_csv('data/typy3.csv', current_merged, 'output2')