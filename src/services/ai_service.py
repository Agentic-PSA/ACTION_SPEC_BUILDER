# src/services/ai_service.py
import json
import os
from functools import lru_cache
import aiohttp
import requests
from openai import OpenAI
import google.generativeai as genai
from httpx import ReadTimeout


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

def ask_gemini(question, prompt):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError(
            "Brak klucza Google Gemini. Podaj go jako parametr lub ustaw zmienną środowiskową GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    
    # print('------------------')
    # for m in genai.list_models():
    #     print(m.name, m.supported_generation_methods)
    # print('------------------')
    # exit()
    model = genai.GenerativeModel("models/gemini-2.5-pro")

    try:
        full_prompt = (
            f"{prompt}\n\n"
            f"Dane wejściowe do analizy:\n\n{question}\n\n"
            "IMPORTANT: Your response must be a valid, complete JSON object. "
            "Don't include Markdown formatting like ```json or ``` in your response. "
            "Don't truncate your response."
        )
        response = model.generate_content(
            full_prompt,
            safety_settings=None,  # opcjonalnie usunięcie filtrów bezpieczeństwa
            generation_config={
                "temperature": 0.0,
                "max_output_tokens": 30000
            }
        )
        #print("-----ask_gemini----")
        #print(full_prompt)
        raw_response = response.text.strip()

        # Usuwanie formatowania Markdown, jeśli występuje
        cleaned_response = raw_response.strip()
        if cleaned_response.startswith('```json'):
            cleaned_response = cleaned_response.replace('```json', '', 1).strip()
        elif cleaned_response.startswith('```'):
            cleaned_response = cleaned_response.replace('```', '', 1).strip()

        if cleaned_response.endswith('```'):
            cleaned_response = cleaned_response.rsplit('```', 1)[0].strip()

        return cleaned_response
    except ReadTimeout:
        print("⏳ Timeout - serwer nie odpowiedział na czas (5 minut)")
        return "⏳ Timeout - serwer nie odpowiedział na czas (5 minut)"



def ask_gpt_aka(question, prompt, api_key=GPT_KEY):
    return ask_gemini(question, prompt)
    """
    Wysyła zapytanie do modelu GPT-4.1 przez OpenAI API i zwraca odpowiedź.

    Args:
        question: Dane wejściowe
        prompt: Instrukcja dla AI
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

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",  # Używamy modelu GPT-4.1
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user",
                "content": f"Dane wejściowe do analizy:\n\n{question}\n\nIMPORTANT: Your response must be a valid, complete JSON object. Don't include markdown formatting like ```json or ``` in your response. Don't truncate your response"
                }
            ],
            temperature=0.0,  # Ustawiamy niską temperaturę dla bardziej deterministycznych wyników
            max_tokens=30000,  # Maksymalna długość odpowiedzi
            timeout=600 # max 10 minut
        )
        #print(prompt)
        #print(question)

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
    except ReadTimeout:
        print("⏳ Timeout - serwer nie odpowiedział na czas (5 minut)")
        return "⏳ Timeout - serwer nie odpowiedział na czas (5 minut)"

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


def ai_analyze_and_create_form(category, section, current_structure, data, filename_prefix, save_function, max_attempts=2):
    """
    Analizuje dane specyfikacji przy użyciu AI i zapisuje wynik.

    Args:
        current_structure: Aktualna formatka
        data: Dane do analizy
        filename_prefix: Prefiks nazwy pliku do zapisu
        save_function: Funkcja do zapisywania danych
        final: Czy to jest ostateczna analiza (wpływa na liczbę wymaganych przykładów)
        max_attempts: Maksymalna liczba prób w przypadku niepoprawnej odpowiedzi

    Returns:
        dict: Wynik analizy AI (jako obiekt JSON) lub pusty słownik w przypadku błędu
    """

    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}". Aktualne zapytanie dotyczy parametrów w sekcji "{section}"

WEJŚCIE: dwa zestawy danych o tych samych strukturach - parametry oraz przykładowe wartości parametrów
W pierwszym zestawie mamy aktualną formatkę opisową, w drugim nowo znalezione parametry 
Struktura danych wejściowych:
{{
    "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
    "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
}}

WYJŚCIE: Przetworzony drugi zestaw danych, tak aby zamiast przykładowych wartości była jedna z odpowiedzi: słowo "NOWA" LUB nazwa parametru z pierwszego zestawu danych, dla którego można dodać mapowanie (bezpośrednio, nie jako tablica)
Struktura danych wyjściowych:
{{
    "Pierwszy parametr": "NOWA",
    "Drugi parametr": "Inny parametr z pierwszego zestawu"
}}

Surowe zasady (należy ich ściśle przestrzegać):
 1. Przykłady podane w podpowiedzi służą wyłącznie do celów ilustracyjnych. Nie stanowią one części rzeczywistego WEJŚCIA. Należy brać pod uwagę wyłącznie atrybuty obecne w pliku JSON użytkownika. Nie należy wprowadzać ani kopiować atrybutów z przykładów.
 2. Używaj **parametrów** do grupowania decyzji. Nie traktuj przykładowych wartości jako nazw parametrów.
 3. Przykładowe wartości służą wyłącznie zapobieganiu błędnemu grupowaniu, a nie uzasadnianiu grupowania.
    - Jeśli dwie nazwy parametrów wyglądają na zduplikowane, można sprawdzić na przykładach, czy ich wartości wyraźnie się różnią (w takim przypadku nie należy ich grupować).
    - Nigdy nie grupuj parametrów wyłącznie na podstawie tego, że ich przykłady wyglądają podobnie lub identycznie.
 5. NIE łącz parametrów w których są wyrażenia wskazujące na całkiem inną cechę np. 
    - "brutto" nie łącz z "netto"
    - "z podstawą" nie łącz z "bez podstawy"
    - "poziomy" nie łącz z "pionowy"
    - "min" nie łącz z "max"
    Należy traktować je jako odrębne parametry, nawet jeśli nazwa podstawowa wygląda podobnie.
    Parametry opisujące różne poziomy szczegółowości tej samej cechy (np. „typ karty graficznej” i „model karty graficznej”) traktuj jako odrębne, jeśli wartości nie są identyczne.
    Parametry opisujące kolory traktuj jako odrębne (nie łącz parametrów jeśli wśród wartości znajdują się kreatywne, marketingowe nazwy kolorów)
 6. Preferuj **konserwatywne grupowanie**: w razie wątpliwości NIE grupuj.
 7. Wynik musi być **wyłącznie prawidłowym JSON**, bez wyjaśnień, bez dodatkowego tekstu, bez końcowych przecinków.
 8. Zachowaj deterministyczność wyników.

Teraz przetwórz dane wprowadzone przez użytkownika (JSON) i zwróć tylko wymagane dane wyjściowe JSON.

"""

    question = json.dumps(current_structure, ensure_ascii=False, indent=2) + "\n\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n\n"

    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)

            # Zapisz surową odpowiedź dla celów diagnostycznych
            # save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response.json')

            try:
                # Próba analizy JSON
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
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


def ai_add_main_data(category, current_structure, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}".
Struktura danych wejściowych:
{{
    "Sekcja 1": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }}
}}
Na podstawie przesłanej formatki zdefiniuj, które pola powinny znaleźć się w sekcji Dane podstawowe. 
Są to kluczowe parametry, po których najczęściej dokonuje się wyboru danego produktu. 
Liczba pól powinna być ograniczona – wybierz tylko te najważniejsze, które realnie wpływają na decyzję zakupową. 
Pamiętaj, że wszystkie pozostałe pola nadal będą widoczne w szczegółowym opisie poniżej, więc tu mają być wyeksponowane tylko najważniejsze informacje.

WYJŚCIE: Struktura danych, w których kluczem jest nazwa parametru, a wartością nazwa sekcji, do której należy
Struktura danych wyjściowych:
{{
    "Pierwszy parametr": "Sekcja 1",
    "Drugi parametr": "Sekcja 3"
}}

Now process the user input (JSON) and return only the required JSON output.

"""
    question = json.dumps(current_structure, ensure_ascii=False, indent=2)+ "\n\n"
    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)
            try:
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")
                save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response_ERROR.json')
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")

    return {}


def ai_remove_duplicates(category, current_structure, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}".

Struktura danych wejściowych:
{{
    "Sekcja 1": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }}
}}

Twoje zadanie:

1. Zidentyfikuj parametry w sekcji, które **nie pasują do tej sekcji** i zarekomenduj ich usunięcie lub przesunięcie.
   - Na przykład: parametr "kolor" nie powinien znajdować się w sekcji "Wymiary" czy "Wydajność" – wtedy zarekomenduj `PRZESUN DO <istniejąca sekcja>` lub `USUN`.
2. Znajdź duplikaty parametrów między sekcjami.
   - Jeśli parametr występuje w kilku sekcjach, wybierz **najbardziej pasujące wystąpienie** do pozostawienia (`ZOSTAW`) i zarekomenduj usunięcie lub przesunięcie pozostałych.
   - Pamiętaj: parametr w jednej sekcji np. „Oparcie krzesła” nie jest duplikatem tego samego parametru w innej sekcji np. „Siedzisko krzesła”.
3. **Nie usuwaj wszystkich wystąpień zdublowanego parametru** – zawsze pozostaw przynajmniej jedno.
4. **Nie twórz nowych sekcji** – przesuwaj parametry tylko do istniejących sekcji.
5. Każdą decyzję uzasadnij w kilku słowach, np. „parametr nie pasuje do sekcji”, „najlepiej pasuje do tej sekcji”, itp.

WYJŚCIE:
- Przetworzony zestaw danych wejściowych zawierający **tylko parametry, dla których rekomendujesz zmianę/usunięcie/przesunięcie**.
- Zamiast przykładowych wartości podaj powód swojej decyzji.
- Użyj formatu:
  - `USUN - powód usunięcia`
  - `ZOSTAW - powód pozostawienia`
  - `PRZESUN DO <nazwa_sekcji> - powód przesunięcia`
     * nazwa sekcji w poleceniu PRZESUN DO musi być zawsze zapisana w nawiasach trójkątnych < >. Jeśli ich zabraknie, odpowiedź jest niepoprawna.
- Zachowaj strukturę formatki (atrybuty powinny znajdować się w odpowiednich sekcjach).

Struktura danych wyjściowych (dane do potencjalnego usunięcia):
{{
    "Sekcja 1": {{
        "Drugi parametr": "USUN - powód usunięcia, np. parametr nie pasuje do sekcji",
        "Trzeci parametr": "PRZESUN DO <Sekcja 2> - parametr jest odpowiedni dla Sekcji 2"
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": "USUN - powód usunięcia, np. podwojone wystąpienie",
        "Piąty parametr": "ZOSTAW - powód pozostawienia, np. najbardziej pasujący z trzech wystąpień"
    }}
}}

Now process the user input (JSON) and return only the required JSON output.

"""
    question = json.dumps(current_structure, ensure_ascii=False, indent=2)+ "\n\n"
    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)
            try:
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")
                save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response_ERROR.json')
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")

    return {}

def ai_set_order(category, current_structure, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}".
Struktura danych wejściowych:
{{
    "Sekcja 1": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
    }}
}}

Twoje zadanie:

1. Zdefiniuj, które sekcje i atrybuty są najważniejsze i powinny być prezentowane jako pierwsze.
2. Zmień tylko kolejność sekcji i kolejność atrybutów w sekcji.
3. **Nie usuwaj żadnych sekcji ani atrybutów.**
4. Sekcja związana z wagą **powinna być umieszczona jako przedostatnia**.
   - Jeśli atrybuty związane z wagą występują w innych sekcjach, **pozostaw je tam**, nie przenoś ani nie usuwaj.
   - Możesz przesuwać atrybuty związane z wagą w ramach własnej sekcji, aby ustawić je w logicznej kolejności.
5. Sekcja związana z wymiarami **powinna być umieszczona jako ostatnia**.
   - Jeśli atrybuty związane z wymiarami występują w innych sekcjach, **pozostaw je tam**, nie przenoś ani nie usuwaj.
   - Możesz przesuwać atrybuty związane z wymiarami w ramach własnej sekcji, aby ustawić je w logicznej kolejności.
6. **Nie twórz żadnych nowych sekcji**. Wykorzystuj tylko sekcje już istniejące w danych wejściowych.
7. Struktura danych wyjściowych powinna być taka sama jak wejściowa, ale z poprawną kolejnością sekcji i atrybutów.
8. Jeśli któryś z atrybutów oznacza kolory, a wśród wartości znajdują się kreatywne, marketingowe nazwy kolorów to dodaj do listy wartości odpowiadający im kolor podstawowy lub powszechnie używany.
   Używaj tylko podstawowych kolorów: czerwony, niebieski, zielony, żółty, pomarańczowy, różowy, fioletowy, brązowy, czarny, biały, szary.

Now process the user input (JSON) and return only the required JSON output.

"""
    question = json.dumps(current_structure, ensure_ascii=False, indent=2)+ "\n\n"
    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)
            try:
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")
                save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response_ERROR.json')
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")

    return {}


def ai_sugest_section_names(category, current_structure, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}".
Struktura danych wejściowych:
{{
    "Sekcja 1": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
    }}
}}
Na podstawie przesłanej formatki zaproponuj nowe nazwy tych sekcji, których nazwy wydają się być nieadekwatne do danych.
Nie zmieniaj wszystkich nazw - zaproponuj zmiany tylko dla tych najmniej adekwatnych.

Struktura danych wyjściowych    :
{{
    "Sekcja 1": "Nowa nazwa sekcji 1",
    "Sekcja 3": "Nowa nazwa sekcji 3"
}}

Now process the user input (JSON) and return only the required JSON output.

"""
    question = json.dumps(current_structure, ensure_ascii=False, indent=2)+ "\n\n"
    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)
            try:
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")
                save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response_ERROR.json')
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")

    return {}

def ai_remove_excess_sections(category, current_structure, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}".
Celem jest zmniejszenie liczby danych używanych do filtrowania i wyszukiwania, aby przyspieszyć działanie systemu.

Struktura danych wejściowych:
{{
    "Sekcja 1": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"]
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
        "Drugi parametr": ["przykładowa wartość 1", "przykładowa wartość 2"],
    }}
}}

Twoje zadanie:
Na podstawie formatki wskaż parametry, które można usunąć, ponieważ:
- wyszukiwania po tych parametrach są bardzo rzadkie,
- wyszukiwania po tych parametrach nic nie wnoszą,
- parametry są nadmiarowe, wtórne, oczywiste lub nieprzydatne w procesie wyboru produktu,
- parametr posiada wartości niskiej jakości (np. powtarzalne, mało informacyjne).

Przykłady typowych parametrów kwalifikujących się do usunięcia:
- parametry kosmetyczne bez znaczenia przy wyszukiwaniu,
- parametry identyczne dla większości produktów,
- parametry nieużywane przez użytkowników (np. w logach zapytań),
- parametry zbyt szczegółowe lub technicznie nieistotne.

Zasady:
1. Nigdy nie usuwaj wszystkich parametrów z jednej sekcji — minimum jeden musi pozostać.
2. Jeśli nie masz pewności, nie rekomenduj usunięcia.
3. Nie przesuwaj parametrów między sekcjami.
4. Nie dodawaj nowych sekcji ani parametrów.
5. Zwracasz tylko listę parametrów proponowanych do usunięcia (żadnych pozostawionych).

Struktura danych wyjściowych (odpowiedz dokładnie w tym formacie):
{{
    "Sekcja 1": {{
        "Drugi parametr": "USUN - powód usunięcia, np. wszystkie produkty mają ten parametr ",
    }},
    "Sekcja 2": {{
        "Pierwszy parametr": "USUN - powód usunięcia, np. wyszukiwania po tych parametrach są bardzo rzadkie",
        "Piąty parametr": "USUN - powód usunięcia ozosatwienia, np. wyszukiwania po tych parametrach nic nie wnoszą"
    }}
}}

Now process the user input (JSON) and return only the required JSON output.

"""
    question = json.dumps(current_structure, ensure_ascii=False, indent=2)+ "\n\n"
    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)
            try:
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
                return ai_json
            except json.JSONDecodeError as e:
                print(f"Próba {attempt + 1}/{max_attempts}: Odpowiedź AI nie jest poprawnym JSONem: {str(e)}")
                save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response_ERROR.json')
        except Exception as e:
            print(f"Błąd podczas analizy AI dla {filename_prefix}: {str(e)}")

    return {}





##### NOWE
def ai_analyze_and_create_form_new(category, section, section_data, filename_prefix, save_function, max_attempts=2):
    prompt = f"""
Analizujesz formatkę opisową produktów w kategorii "{category}". Aktualne zapytanie dotyczy parametrów w sekcji "{section}"

Struktura danych wejściowych:
{{
    "Parametr A": ["wartość 1", "wartość 2"],
    "Parametr B": ["wartość X", "wartość Y"]
}}

Twoim zadaniem jest zwrócić strukturalną decyzję, czy:
- dany parametr powinien pozostać osobno („ZOSTAW”),
- czy należy go połączyć z innym istniejącym parametrem (np. "Parametr B": "Parametr A").

WYJŚCIE: Przetworzony zestaw danych, tak aby zamiast przykładowych wartości była jedna z odpowiedzi: 
- słowo ZOSTAW
- LUB nazwa parametru z którym należy połączyć aktualne wartości

Struktura danych wyjściowych:
{{
    "Parametr A": "ZOSTAW",
    "Parametr B": "Parametr A"
}}

Surowe zasady (stosuj dosłownie):

1. Używaj **nazw parametrów jako głównej wskazówki**, ale weryfikuj je również przez wartości.  
2. Nie łącz parametrów o różnych typach wartości (zakres vs wartość ścisła, różne jednostki, różne poziomy szczegółowości).  
3. Jeśli nazwy parametrów sugerują tę samą cechę i wartości mają częściowe pokrycie, połącz je.  
   - Nie muszą mieć identycznej listy wartości, wystarczy że typ wartości jest spójny.  
   - **Wyjątek:** wartości zakresowe nigdy nie łącz z wartościami ścisłymi.
4. Parametry opisujące różne poziomy tej samej cechy traktuj jako odrębne, jeśli wartości nie są identyczne.  
5. Jeśli dwa parametry mają takie same lub bardzo podobne nazwy, ale wartości wyraźnie różnią się semantycznie, NIE łącz ich.  
6. Nie łącz parametrów, które oznaczają inne cechy („brutto” ≠ „netto”, „mikrofon” ≠ „rodzaj mikrofonu”, „poziomy” ≠ „pionowy” itp.).  
7. Nie łącz parametrów, które oznaczają kolory (które zawierają kolory podstawowe jak i jeśli wśród wartości znajdują się kreatywne, marketingowe nazwy kolorów)
8. Preferuj konserwatywne grupowanie – jeśli nie jesteś pewny, pozostaw parametr osobno.  
9. Jeśli już łączysz, wybierz najbardziej zrozumiałą nazwę parametru w zestawie.  
10. Wynik musi być **wyłącznie prawidłowym JSON**, bez wyjaśnień, bez dodatkowego tekstu, bez końcowych przecinków.  
11. Odpowiedź musi być deterministyczna: te same dane wejściowe → ten sam wynik.


Przetwórz dane wejściowe JSON i zwróć wyłącznie wymagane dane wyjściowe JSON.


"""

    question = json.dumps(section_data, ensure_ascii=False, indent=2) + "\n\n"

    for attempt in range(max_attempts):
        try:
            ai_response = ask_gpt_aka(question, prompt)

            # Zapisz surową odpowiedź dla celów diagnostycznych
            # save_function({"raw_response": ai_response}, f'{filename_prefix}_raw_ai_response.json')

            try:
                # Próba analizy JSON
                ai_json = json.loads(ai_response)
                #save_function(ai_json, f'{filename_prefix}_ai_analysis.json')
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



