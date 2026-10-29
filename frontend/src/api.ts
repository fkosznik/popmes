export function requestKey(): string {
  // crypto.randomUUID requires HTTPS; LAN HTTP previews still need unique IDs.
  const a = crypto.getRandomValues(new Uint8Array(16));
  a[6] = (a[6] & 15) | 64;
  a[8] = (a[8] & 63) | 128;
  const h = [...a].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
const fieldLabels: Record<string, string> = {
  name: "Nazwa",
  code: "Kod",
  sku: "SKU",
  email: "E-mail",
  phone: "Telefon",
  contact: "Kontakt",
  tax_id: "NIP",
  address: "Adres",
  delivery_addresses: "Adres dostawy",
  postal_code: "Kod pocztowy",
  city: "Miasto",
  street: "Ulica",
  house_number: "Numer domu",
  apartment: "Numer lokalu",
  quantity: "Ilość",
  weight_g: "Gramatura",
  password: "Hasło",
  password_repeat: "Powtórzenie hasła",
  current_password: "Obecne hasło",
  username: "Login",
  unit: "Jednostka",
};
const englishErrors: Record<string, string> = {
  "This field is required.": "Uzupełnij to pole.",
  "This field may not be blank.": "To pole nie może być puste.",
  "This field may not be null.": "Uzupełnij to pole.",
  "Enter a valid email address.": "Podaj poprawny e-mail.",
  "A valid integer is required.": "Podaj liczbę całkowitą.",
  "A valid number is required.": "Podaj liczbę.",
  "Not found.": "Nie znaleziono.",
  "Failed to fetch": "Brak połączenia. Zachowano formularz — spróbuj ponownie.",
};
function polish(text: string) {
  if (englishErrors[text]) return englishErrors[text];
  const longer = text.match(/^Ensure this field has no more than (\d+) characters\.$/);
  if (longer) return `Wpisz najwyżej ${longer[1]} znaków.`;
  if (text.includes("already exists")) return "Taka wartość już istnieje. Wybierz inną.";
  if (text.startsWith("This password is too short"))
    return "Hasło jest za krótkie. Musi mieć co najmniej 10 znaków.";
  if (text === "This password is too common.")
    return "To hasło jest zbyt popularne. Wybierz inne.";
  if (text === "This password is entirely numeric.")
    return "Hasło nie może składać się z samych cyfr.";
  return text;
}
function readable(value: unknown, key = ""): string {
  if (typeof value === "string") {
    const message = polish(value);
    const label = fieldLabels[key];
    return label ? `${label}: ${message}` : message;
  }
  if (Array.isArray(value)) return value.map((item) => readable(item, key)).join(" ");
  if (value && typeof value === "object")
    return Object.entries(value)
      .map(([name, item]) =>
        readable(item, name === "detail" || name === "non_field_errors" || /^\d+$/.test(name) ? key : name),
      )
      .filter(Boolean)
      .join(" ");
  return "Nie udało się wykonać operacji.";
}
export async function api<T>(
  path: string,
  data?: unknown,
  key?: string,
): Promise<T> {
  const csrf =
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("csrftoken="))
      ?.split("=")[1] || "";
  const form = data instanceof FormData;
  const response = await fetch("/api/" + path, {
    method: data === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: {
      ...(form ? {} : { "Content-Type": "application/json" }),
      ...(data === undefined
        ? {}
        : {
            "X-CSRFToken": decodeURIComponent(csrf),
            "Idempotency-Key": key || requestKey(),
          }),
    },
    body: data === undefined ? undefined : form ? data : JSON.stringify(data),
  });
  const content = await response
    .json()
    .catch(() => ({ detail: "Serwer nie zwrócił poprawnej odpowiedzi." }));
  if (!response.ok) throw new Error(readable(content));
  return content as T;
}
