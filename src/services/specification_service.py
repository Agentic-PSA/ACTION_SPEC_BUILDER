# src/services/specification_service.py
import json


def merge_specifications(spec1, spec2):
    if not spec1:
        return spec2
    if not spec2:
        return spec1

    merged_spec = []
    spec1_sections = {section["section_name"]["EN"]: section for section in spec1}

    for section in spec2:
        section_name = section["section_name"]["EN"]
        if section_name in spec1_sections:
            merged_attributes = spec1_sections[section_name]["attributes"]
            for attr in section["attributes"]:
                if attr not in merged_attributes:
                    merged_attributes.append(attr)
            merged_section = {
                "section_name": section["section_name"],
                "attributes": merged_attributes
            }
            spec1_sections[section_name] = merged_section
        else:
            spec1_sections[section_name] = section

    return list(spec1_sections.values())


def combine_specifications_with_values(merged_specification, specification_values, language="PL",
                                       duplicate_mapping=None):
    combined = []

    for section in merged_specification:
        section_name = section["section_name"].get(language)
        if not section_name:
            continue

        combined_section = {"section_name": section_name, "attributes": []}

        # Pobierz mapę duplikatów dla tej sekcji, jeśli istnieje
        section_mapping = duplicate_mapping.get(section_name, {}) if duplicate_mapping else {}

        # Tworzymy odwrotną mapę: duplikat -> nazwa kanoniczna
        reverse_mapping = {}
        for canonical_name, duplicates in section_mapping.items():
            for duplicate in duplicates:
                reverse_mapping[duplicate] = canonical_name

        # Tworzymy słownik wszystkich przykładów dla każdego atrybutu (łącznie z duplikatami)
        all_examples = {}

        # Pierwsza pętla - zbieramy wszystkie przykłady
        for attribute in section["attributes"]:


            attribute_name = attribute.get(language)
            if 'wyświetlacz' == section_name.lower():
                print(attribute_name)
            if not attribute_name:
                continue

            if attribute_name not in all_examples:
                all_examples[attribute_name] = []

            for panel_values in specification_values:
                values_for_lang = panel_values.get(language, {})
                section_values = values_for_lang.get(section_name, {})
                value = section_values.get(attribute_name)
                if value is not None and value not in all_examples[attribute_name]:
                    if 'wyświetlacz' == section_name.lower():
                        print(value)
                    all_examples[attribute_name].append(value)
        if 'wyświetlacz' == section_name.lower():
            print(all_examples)

        duplicate_examples_from_values = {}
        for duplicate_name, canonical_name in reverse_mapping.items():
            duplicate_examples_from_values[duplicate_name] = []
            for panel_values in specification_values:
                values_for_lang = panel_values.get(language, {})
                section_values = values_for_lang.get(section_name, {})
                value = section_values.get(duplicate_name)
                if value is not None and value not in duplicate_examples_from_values[duplicate_name]:
                    duplicate_examples_from_values[duplicate_name].append(value)
        if 'wyświetlacz' == section_name.lower():
            print(duplicate_examples_from_values)
        # Druga pętla - przenosimy przykłady z duplikatów do kanonicznych nazw

        for duplicate_name, canonical_name in reverse_mapping.items():
            if 'wyświetlacz' == section_name.lower():
                print('|| ', duplicate_name)
            examples_to_add = duplicate_examples_from_values.get(duplicate_name, [])
            if canonical_name not in all_examples:
                all_examples[canonical_name] = []

            for example in examples_to_add:
                if example not in all_examples[canonical_name]:
                    if 'wyświetlacz' == section_name.lower():
                        print('||| ', example)
                    all_examples[canonical_name].append(example)






        if 'wyświetlacz' == section_name.lower():
            print('____________________________')
            print(all_examples)
        # Trzecia pętla - tworzymy finalne atrybuty pod kanonicznymi nazwami
        processed_attributes = set()
        for attribute_name in all_examples.keys():
            if attribute_name in processed_attributes:
                continue

            processed_attributes.add(attribute_name)
            examples = all_examples.get(attribute_name, [])

            # Normalizacja "Tak"/"Nie"
            has_yes = any(isinstance(e, str) and e.lower() == "tak" for e in examples)
            has_no = any(isinstance(e, str) and e.lower() == "nie" for e in examples)
            if has_yes and not has_no:
                examples.append("Nie")
            elif has_no and not has_yes:
                examples.append("Tak")

            normalized_examples = []
            has_added_yes = has_added_no = False
            for e in examples:
                if isinstance(e, str) and e.lower() == "tak":
                    if not has_added_yes:
                        normalized_examples.append("Tak")
                        has_added_yes = True
                elif isinstance(e, str) and e.lower() == "nie":
                    if not has_added_no:
                        normalized_examples.append("Nie")
                        has_added_no = True
                else:
                    normalized_examples.append(e)

            # Usuwanie duplikatów dla pozostałych wartości
            final_examples = []
            seen_values = set()
            for e in normalized_examples:
                if isinstance(e, str):
                    key = e.lower()
                    if key not in seen_values:
                        seen_values.add(key)
                        final_examples.append(e)
                else:
                    if e not in final_examples:
                        final_examples.append(e)
            if 'wyświetlacz' == section_name.lower():
                print('||| ', final_examples)
            combined_section["attributes"].append({
                "name": attribute_name,
                "examples": final_examples
            })

        combined.append(combined_section)

    return combined



# src/services/specification_service.py - dodaj nową funkcję

def normalize_specification(specification, duplicate_mapping):
    """
    Normalizuje specyfikację zamieniając nazwy duplikatów na nazwy kanoniczne.

    Args:
        specification: Lista sekcji specyfikacji do normalizacji
        duplicate_mapping: Mapa duplikatów w formacie {sekcja: {nazwa_kanoniczna: [duplikat1, duplikat2]}}

    Returns:
        list: Znormalizowana specyfikacja
    """
    if not duplicate_mapping:
        return specification

    normalized_spec = []

    for section in specification:
        if "section_name" in section:
            # Dla struktury surowej specyfikacji (słownik z tłumaczeniami)
            if isinstance(section["section_name"], dict):
                # Używamy wartości w języku PL jako klucza w mapie duplikatów
                section_name = section["section_name"].get("PL", "")
                attributes_key = "attributes"
                name_key = "PL"  # Atrybuty również są słownikami tłumaczeń
            else:
                # Dla struktury ze skombinowanymi przykładami
                section_name = section["section_name"]
                attributes_key = "attributes"
                name_key = "name"
        else:
            # Dla innego formatu (np. z AI)
            section_name = section.get("section", "")
            attributes_key = "attributes"
            name_key = "name"

        section_mapping = duplicate_mapping.get(section_name, {})

        if not section_mapping:
            normalized_spec.append(section)
            continue

        # Tworzymy odwrotną mapę: duplikat -> nazwa kanoniczna
        reverse_mapping = {}
        for canonical_name, duplicates in section_mapping.items():
            for duplicate in duplicates:
                reverse_mapping[duplicate] = canonical_name

        # Tworzymy nową listę atrybutów, zamieniając duplikaty
        attributes_by_name = {}

        for attr in section.get(attributes_key, []):
            # Obsługa różnych struktur atrybutów
            if isinstance(attr, dict) and name_key in attr:
                if isinstance(attr[name_key], str):
                    attr_name = attr[name_key]
                elif isinstance(attr[name_key], dict):
                    # Dla złożonych struktur
                    attr_name = attr[name_key].get("PL", "")
                else:
                    attr_name = ""
            else:
                attr_name = ""

            # Jeśli atrybut to duplikat, zmień nazwę na kanoniczną
            if attr_name in reverse_mapping:
                canonical_name = reverse_mapping[attr_name]

                # Jeśli już istnieje atrybut o nazwie kanonicznej, połącz wartości
                if canonical_name in attributes_by_name:
                    canonical_attr = attributes_by_name[canonical_name]

                    # Jeśli mamy examples, łączymy je
                    if "examples" in attr and "examples" in canonical_attr:
                        for example in attr["examples"]:
                            if example not in canonical_attr["examples"]:
                                canonical_attr["examples"].append(example)

                    continue  # Pomijamy duplikat, bo już połączyliśmy wartości

                # Zachowujemy oryginalny atrybut, ale zmieniamy nazwę
                if isinstance(attr[name_key], str):
                    attr[name_key] = canonical_name
                elif isinstance(attr[name_key], dict):
                    attr[name_key]["PL"] = canonical_name

            # Dodajemy atrybut do tymczasowego słownika z odpowiednim kluczem
            if isinstance(attr[name_key], str):
                key = attr[name_key]
            elif isinstance(attr[name_key], dict):
                key = attr[name_key].get("PL", "")
            else:
                key = ""

            attributes_by_name[key] = attr

        # Odtwarzamy listę atrybutów
        new_attributes = list(attributes_by_name.values())

        # Tworzymy nową sekcję z unikalnymi atrybutami
        if "section_name" in section:
            new_section = {
                "section_name": section["section_name"],
                "attributes": new_attributes
            }
        else:
            new_section = {
                "section": section_name,
                "attributes": new_attributes
            }

        normalized_spec.append(new_section)

    return normalized_spec