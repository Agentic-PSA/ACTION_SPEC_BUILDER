# src/services/form_service.py
import os
import json


def build_form(trans_lang, llm_form, categories, include_values=True):
    """
    Buduje formatkę w docelowym formacie.

    :param trans_lang: słownik tłumaczeń (sekcje i atrybuty)
    :param ordered: dane w formacie sekcja -> atrybut -> lista wartości
    :param categories: wartość dla pola "secondary_key"
    :param include_values: jeśli True, dodaje pole "values" z przykładami
    :return: lista z jedną strukturą JSON
    """
    output = {
        "top_level_key": "attributes",
        "secondary_key": categories,
        "value": []
    }

    for section_pl, attrs in llm_form.items():
        section_obj = {
            "section_name": trans_lang.get(section_pl, {"PL": section_pl}),
            "attributes": []
        }
        for attr_pl, values in attrs.items():
            attr_obj = trans_lang.get(attr_pl, {"PL": attr_pl})
            attr_obj = dict(attr_obj)  # kopiujemy
            if include_values:
                attr_obj["values"] = values
            section_obj["attributes"].append(attr_obj)
            trans_lang[attr_obj["PL"]] = attr_obj
        output["value"].append(section_obj)

    return [output]



