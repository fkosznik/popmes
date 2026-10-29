"""Turn API errors into one Polish sentence. Field names are not shown in English."""

import re

from rest_framework.views import exception_handler

FIELD_LABELS = {
    "name": "Nazwa",
    "code": "Kod",
    "sku": "SKU",
    "email": "E-mail",
    "phone": "Telefon",
    "contact": "Kontakt",
    "tax_id": "NIP",
    "address": "Adres",
    "delivery_addresses": "Adres dostawy",
    "postal_code": "Kod pocztowy",
    "city": "Miasto",
    "street": "Ulica",
    "house_number": "Numer domu",
    "apartment": "Numer lokalu",
    "quantity": "Ilość",
    "weight_g": "Gramatura",
    "packaging": "Opakowanie",
    "instruction": "Instrukcja",
    "color": "Kolor",
    "unit": "Jednostka",
    "username": "Login",
    "password": "Hasło",
    "password_repeat": "Powtórzenie hasła",
    "current_password": "Obecne hasło",
    "category_id": "Kategoria",
    "supplier_id": "Dostawca",
    "customer_id": "Klient",
    "variant_id": "Wariant",
    "product": "Produkt",
    "active": "Aktywny",
}

EXACT = {
    "This field is required.": "Uzupełnij to pole.",
    "This field may not be blank.": "To pole nie może być puste.",
    "This field may not be null.": "Uzupełnij to pole.",
    "Enter a valid email address.": "Podaj poprawny e-mail.",
    "A valid integer is required.": "Podaj liczbę całkowitą.",
    "A valid number is required.": "Podaj liczbę.",
    "This field must be unique.": "Taka wartość już istnieje. Wybierz inną.",
    "You do not have permission to perform this action.": "Brak uprawnień do tej czynności.",
    "Not found.": "Nie znaleziono.",
    "This password is too short. It must contain at least 10 characters.": "Hasło jest za krótkie. Musi mieć co najmniej 10 znaków.",
    "This password is too common.": "To hasło jest zbyt popularne. Wybierz inne.",
    "This password is entirely numeric.": "Hasło nie może składać się z samych cyfr.",
}


def polish_message(value):
    text = str(value).strip()
    if text in EXACT:
        return EXACT[text]
    longer = re.fullmatch(r"Ensure this field has no more than (\d+) characters\.", text)
    if longer:
        return f"Wpisz najwyżej {longer.group(1)} znaków."
    shorter = re.fullmatch(r"Ensure this field has at least (\d+) characters\.", text)
    if shorter:
        return f"Wpisz co najmniej {shorter.group(1)} znaków."
    if "already exists" in text:
        return "Taka wartość już istnieje. Wybierz inną."
    if text.startswith("This password is too short"):
        return "Hasło jest za krótkie. Musi mieć co najmniej 10 znaków."
    return text


def flatten_errors(data, label=""):
    if isinstance(data, dict):
        lines = []
        for key, value in data.items():
            name = "" if str(key).isdigit() or key in {"detail", "non_field_errors"} else FIELD_LABELS.get(str(key), "")
            lines.extend(flatten_errors(value, name or label))
        return lines
    if isinstance(data, list):
        lines = []
        for item in data:
            lines.extend(flatten_errors(item, label))
        return lines
    message = polish_message(data)
    if not message:
        return []
    if label:
        return [f"{label}: {message}"]
    return [message]


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None
    lines = flatten_errors(response.data)
    if lines:
        response.data = {"detail": " ".join(lines)}
    return response
