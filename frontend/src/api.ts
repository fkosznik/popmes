export function requestKey(): string {
  // crypto.randomUUID requires HTTPS; LAN HTTP previews still need unique IDs.
  const a = crypto.getRandomValues(new Uint8Array(16));
  a[6] = (a[6] & 15) | 64;
  a[8] = (a[8] & 63) | 128;
  const h = [...a].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
function readable(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(readable).join(" ");
  if (value && typeof value === "object")
    return Object.entries(value)
      .map(([k, v]) => (k === "detail" ? "" : `${k}: `) + readable(v))
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
