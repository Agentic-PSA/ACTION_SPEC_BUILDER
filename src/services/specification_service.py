# src/services/specification_service.py

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

        # Utwórz odwrotną mapę: duplikat -> nazwa kanoniczna
        reverse_mapping = {}
        for canonical_name, duplicates in section_mapping.items():
            for duplicate in duplicates:
                reverse_mapping[duplicate] = canonical_name

        for attribute in section["attributes"]:
            attribute_name = attribute.get(language)
            if not attribute_name:
                continue

            # Zbieramy wszystkie przykładowe wartości z każdego panel.specification_values
            examples = []
            for panel_values in specification_values:
                values_for_lang = panel_values.get(language, {})
                section_values = values_for_lang.get(section_name, {})

                # Najpierw sprawdź wartość dla normalnej nazwy atrybutu
                value = section_values.get(attribute_name)
                if value is not None:
                    examples.append(value)

                # Jeśli mamy mapę duplikatów, sprawdź również wartości dla duplikatów
                if duplicate_mapping:
                    # Szukaj wszystkich duplikatów tego atrybutu
                    for duplicate, canonical in reverse_mapping.items():
                        if canonical == attribute_name:
                            dup_value = section_values.get(duplicate)
                            if dup_value is not None and dup_value not in examples:
                                examples.append(dup_value)

            # Usuwamy duplikaty
            examples = list(dict.fromkeys(examples))

            combined_section["attributes"].append({
                "name": attribute_name,
                "examples": examples
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