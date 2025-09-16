# src/services/ai_service.py
import json
import requests
from functools import lru_cache
import os
from openai import OpenAI

SONOMA_KEY = "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"
GPT_KEY = "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"

@lru_cache(maxsize=1)
def get_system_prompt(final: bool = False):
    return f"""
    You are an assistant that analyzes structured product specifications and groups only real duplicates / equivalent attribute names **within the same section**.

INPUT: JSON with section -> list of attributes, each attribute has "name" and "examples" (list of example values).

OUTPUT: **Only** a valid JSON object with format:
{{
  "SectionName": {{
    "Canonical attribute name": ["duplicate name A", "duplicate name B", ...],
    ...
  }},
  ...
}}

Hard rules (follow strictly):
0. Examples provided in the prompt are for illustration only. They are never part of the actual INPUT. You must only consider attributes present in the user's JSON. Do not introduce or copy attributes from the examples.
1. Use **attribute names primarily** for grouping decisions. Do not treat example values as attribute names.
1a. Examples are used only to prevent false grouping, not to justify grouping.
   - If two attribute names look like duplicates, you may consult examples to check whether their values clearly differ (in which case, do not group).
   - Never group attributes solely because their examples look similar or identical.
2. Ignore any attribute that has **fewer than {1 if final else 2} examples** – treat it as unique and do not attempt to group it.
3. Do NOT group attributes that explicitly reference **different connector/types**. Connector keywords (case-insensitive) include at least: hdmi, usb, ethernet, rj-45, rj45, rf, scart, vga, displayport, optical, coaxial, jack, audio, aux. If two names mention different connector words, they must NOT be grouped.
4. For **count-like attributes** (examples are numeric or integer strings): group only when the connector/type token matches (see rule 3) and names are near-synonyms (e.g., "Ilość portów HDMI" ↔ "Liczba złącz HDMI"). Do not group counts of different connector types.
5. Do NOT merge attributes that differ by qualifiers in parentheses (e.g., "(z podstawą)" vs "(bez podstawy)"). Treat them as distinct parameters, even if the base name looks similar.
5a. If attributes differ by the content inside parentheses (e.g., "(vertical)" vs "(horizontal)", "(min)" vs "(max)"), always treat them as distinct attributes. The text inside parentheses is part of the semantic meaning and must not be ignored.
6. Prefer **conservative grouping**: if uncertain, do NOT group. Minimal false positives > minimal false negatives.
7. Choose canonical name using this priority:
   - shortest name without parentheses,
   - if tied: the most generic (no brand/model tokens),
   - if tied: the most frequent occurrence in input.
8. Output must be **valid JSON only**, no explanations, no extra text, no trailing commas.
9. Keep result deterministic.

Example (how you must behave):

INPUT:
{{
  "Zawartość opakowania": [
    {{"name": "W zestawie pilot zdalnego sterowania", "examples": ["Tak", "Nie"]}},
    {{"name": "Pilot zdalnego sterowania", "examples": ["TM2361E", "MR24", "TM2360E", "RC833A"]}},
    {{"name": "Podstawa biurkowa", "examples": ["Tak", "Nie"]}}
  ]
}}
EXPECTED OUTPUT:
{{
  "Zawartość opakowania": {{
    "W zestawie pilot zdalnego sterowania": ["Pilot zdalnego sterowania"],
    "Podstawa biurkowa": []
  }}
}}
Example (how you must behave with few examples):

INPUT:
{{
  "Wyświetlacz": [
    {{"name": "Przekątna ekranu", "examples": ["43\\"", "50\\"", "51\\"", "75\\""]}},
    {{"name": "Długość przekątnej ekranu (cm)", "examples": ["108 cm"]}},
    {{"name": "Przekątna (inch)", "examples": ["43\\"", "50\\"", "55\\"", "65\\""]}},
    {{"name": "Typ HD", "examples": ["Full HD", "HD", "FHD"]}}
  ]
}}
EXPECTED OUTPUT:
{{
  "Wyświetlacz": {{
    "Typ HD": [],
    "Przekątna ekranu": ["Przekątna (inch)"],
    "Długość przekątnej ekranu (cm)": []
  }}
}}
Now process the user input (JSON) and return only the required JSON output.

"""


def ask_sonoma(question, api_key=SONOMA_KEY):
    """
    Wysyła zapytanie do modelu AI i zwraca odpowiedź.

    Args:
        question: Treść zapytania w formacie JSON
        api_key: Klucz API do serwisu OpenRouter

    Returns:
        str: Odpowiedź modelu AI
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost",
        "X-Title": "MyApp"
    }

    data = {
        "model": "openrouter/sonoma-dusk-alpha",
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": f"Here is the input specification data:\n\n{question}"}
        ]
    }

    resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    return resp.json()["choices"][0]["message"]["content"]


def ask_gpt(question, final=False, api_key=GPT_KEY):
    """
    Wysyła zapytanie do modelu GPT-4.1 przez OpenAI API i zwraca odpowiedź.

    Args:
        question: Treść zapytania w formacie JSON
        final: Czy to jest ostateczne zapytanie (wpływa na liczbę wymaganych przykładów)
        api_key: Klucz API do serwisu OpenAI

    Returns:
        str: Odpowiedź modelu AI (oczyszczona z formatowania Markdown)
    """
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "Brak klucza API OpenAI. Podaj go jako parametr lub ustaw zmienną środowiskową OPENAI_API_KEY")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4.1",  # Używamy modelu GPT-4.1
        messages=[
            {"role": "system", "content": get_system_prompt(final)},
            {"role": "user",
             "content": f"Here is the input specification data:\n\n{question}\n\nIMPORTANT: Your response must be a valid, complete JSON object. Don't include markdown formatting like ```json or ``` in your response."}
        ],
        temperature=0.0,  # Ustawiamy niską temperaturę dla bardziej deterministycznych wyników
        max_tokens=30000  # Maksymalna długość odpowiedzi
    )

    raw_response = response.choices[0].message.content

    # Usuwanie formatowania Markdown, jeśli występuje
    cleaned_response = raw_response.strip()
    if cleaned_response.startswith('```json'):
        cleaned_response = cleaned_response.replace('```json', '', 1).strip()
    elif cleaned_response.startswith('```'):
        cleaned_response = cleaned_response.replace('```', '', 1).strip()

    if cleaned_response.endswith('```'):
        cleaned_response = cleaned_response.rsplit('```', 1)[0].strip()

    return cleaned_response
def analyze_and_save(data, filename_prefix, save_function, final=False, max_attempts=2):
    """
    Analizuje dane specyfikacji przy użyciu AI i zapisuje wynik.

    Args:
        data: Dane do analizy
        filename_prefix: Prefiks nazwy pliku do zapisu
        save_function: Funkcja do zapisywania danych
        final: Czy to jest ostateczna analiza (wpływa na liczbę wymaganych przykładów)
        max_attempts: Maksymalna liczba prób w przypadku niepoprawnej odpowiedzi

    Returns:
        dict: Wynik analizy AI (jako obiekt JSON) lub pusty słownik w przypadku błędu
    """
    for attempt in range(max_attempts):
        try:
            # Dodajemy instrukcję o limicie odpowiedzi
            prompt_addition = "\nIMPORTANT: Your response must be a valid, complete JSON object. Don't truncate your response."
            ai_response = ask_gpt(json.dumps(data, ensure_ascii=False) + prompt_addition, final)

            # Zapisz surową odpowiedź dla celów diagnostycznych
            save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response.json')

            try:
                # Próba analizy JSON
                ai_json = json.loads(ai_response)
                save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")

                # Spróbuj wyczyścić odpowiedź - usuń tekst przed i po JSON
                cleaned_response = ai_response.strip()
                if cleaned_response.startswith('```json'):
                    cleaned_response = cleaned_response.replace('```json', '', 1).strip()
                if cleaned_response.endswith('```'):
                    cleaned_response = cleaned_response.rsplit('```', 1)[0].strip()

                # Ponowna próba parsowania
                try:
                    ai_json = json.loads(cleaned_response)
                    save_function(ai_json, f'{filename_prefix}_ai_analysis_cleaned.json')
                    return ai_json
                except json.JSONDecodeError:
                    # Jeśli jesteśmy w ostatniej próbie, zwróć pusty słownik
                    if attempt == max_attempts - 1:
                        print(f"Wszystkie próby nieudane dla {filename_prefix}")
                        error_result = {}
                        save_function({"error": "Invalid JSON response after all attempts",
                                       "response": ai_response},
                                      f'{filename_prefix}_ai_analysis_error.json')
                        return error_result
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")
            if attempt == max_attempts - 1:
                error_result = {}
                save_function({"error": str(e)}, f'{filename_prefix}_ai_analysis_error.json')
                return error_result

    # Jeśli wszystkie próby się nie powiodły, zwróć pusty słownik
    return {}