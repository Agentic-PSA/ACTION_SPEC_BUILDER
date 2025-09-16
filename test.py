import json
from src.services.specification_service import combine_specifications_with_values
from src.routes.etl2 import clean_duplicate_mapping

with open("output/2025-09-16_13-04-16/debug_input_before_combine_batchf_45.json", "r", encoding="utf-8") as f:
    debug_input = json.load(f)
global_duplicate_mapping = debug_input['duplicate_mapping']
global_duplicate_mapping = clean_duplicate_mapping(global_duplicate_mapping)
result = combine_specifications_with_values(
    debug_input['merged_specification'],
    debug_input['all_examples'],
    "PL",
    global_duplicate_mapping
)

with open("debug_result_batch_1.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
