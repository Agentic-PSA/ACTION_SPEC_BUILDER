# src/services/ai_service.py
import json
import os
from functools import lru_cache
import aiohttp
import requests
from openai import OpenAI

SONOMA_KEY = "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"
GPT_KEY = "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"


@lru_cache(maxsize=1)
def get_system_prompt(final: bool = False):
    return f"""You are an assistant that groups only real duplicates of attribute names in structured product specifications.  
Work strictly within the same section.

INPUT: JSON with {{section -> list of {{name, examples}}}}.  
OUTPUT: JSON with format:  
{{
  "SectionName": {{
    "Canonical attribute name": ["duplicate1", "duplicate2", ...],
    ...
  }}
}}

Rules:
0. Use only attribute names from input. Never invent or copy from examples.  
1. Grouping is based on names. Examples are used only to prevent false merges (if values clearly differ, do not group).  
2. Skip attributes with < {{1 if final else 2}} examples.  
3. Do not merge names that mention different connector types (hdmi, usb, ethernet, rj-45, rj45, rf, scart, vga, displayport, optical, coaxial, jack, audio, aux).  
4. For numeric/count attributes: group only if connector type matches and names are synonyms.  
5. Do not merge attributes with qualifiers that change meaning:  
   - (z podstawą) vs (bez podstawy), (min) vs (max), (vertical) vs (horizontal).  
   - Directional words like "pionowy/poziomy" or "w pionie/w poziomie" must be treated as distinct.  
   - "Kąt widzenia" vs "Kąt widzenia w pionie" vs "Kąt widzenia (poziomy)" are different.  
6. Be conservative: if unsure, keep separate.  
7. Canonical name priority:  
   - most descriptive/self-explanatory (even if longer),  
   - if tie: without parentheses,  
   - if tie: most generic (no brand/model tokens),  
   - if tie: most frequent in input.  
8. Output must be valid JSON only, with no comments, no markdown, no trailing commas.  
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


async def ask_sonoma_custom(system_prompt=None, user_prompt=None, api_key=SONOMA_KEY):
    """
    Wysyła zapytanie do modelu AI i zwraca odpowiedź.

    Args:
        system_prompt: Treść promptu systemowego
        user_prompt: Treść promptu użytkownika
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
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post("https://openrouter.ai/api/v1/chat/completions",
                               headers=headers, json=data) as resp:
            response_json = await resp.json()
            return response_json["choices"][0]["message"]["content"]

def ask_gpt_custom(system_prompt, content, model="gpt-4.1", api_key=GPT_KEY):
    """
    Wysyła zapytanie do modelu GPT z niestandardowym promptem systemowym i treścią.

    Args:
        system_prompt: Własny prompt systemowy
        content: Treść zapytania do modelu
        model: Model OpenAI do użycia (domyślnie gpt-5)
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
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ],
        temperature=0.00,  # Niska temperatura dla deterministycznych wyników
        seed= 4944116822809979520,
        max_tokens=32000,  # Maksymalna długość odpowiedzi
        response_format = {"type": "json_object"}
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


def ask_gpt(question, final=False, model="gpt-4.1", api_key=GPT_KEY):
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("Brak klucza API OpenAI.")

    client = OpenAI(api_key=api_key)

    system_prompt = "You are a precise assistant for grouping duplicates of attribute names in product specifications."

    full_prompt = f"""{get_system_prompt(final)}

Here is the input specification data:

{question}

IMPORTANT: Your response must be a valid, complete JSON object. 
Don't include markdown formatting like ```json or ``` in your response.
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt},
        ],
        temperature=0.0,
        max_tokens=30000
    )

    raw_response = response.choices[0].message.content.strip()

    # Czyścimy ewentualne ```json
    if raw_response.startswith("```"):
        raw_response = raw_response.split("```", 1)[-1].strip()
        if raw_response.endswith("```"):
            raw_response = raw_response[:-3].strip()

    return raw_response


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
