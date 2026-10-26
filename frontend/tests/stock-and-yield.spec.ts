import { test, expect } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByLabel("Login", { exact: true })
    .fill(process.env.POP_TEST_USER || "admin");
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(process.env.POP_TEST_PASSWORD || "Local-test-Only-925!");
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await expect(page.getByRole("heading", { name: /Cześć/ })).toBeVisible();
}

test("magazyn sortuje kolumny, a przyjęcie szuka produktu", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Magazyn", exact: true }).click();
  const weight = page.getByRole("columnheader", { name: "Gramatura" }).first();
  await weight.getByRole("button").click();
  await expect(weight).toHaveAttribute("aria-sort", "ascending");
  await weight.getByRole("button").click();
  await expect(weight).toHaveAttribute("aria-sort", "descending");
  await page.getByRole("columnheader", { name: "Pozycja" }).first().getByRole("button").click();
  await page.getByRole("button", { name: "Przyjęcie towaru" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Szukaj produktu")).toBeVisible();
  await expect(dialog.getByRole("combobox")).toHaveCount(0);
  await dialog.getByLabel("Szukaj produktu").fill("cuk");
  await expect(dialog.getByRole("listbox")).toBeVisible();
});

test("zgłoszenie produkcji nie ogranicza ilości do zamówienia", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "Produkcja", exact: true }).click();
  const report = page
    .getByRole("button", { name: "Zgłoś opakowania", disabled: false })
    .first();
  await expect(report).toBeVisible();
  await report.click();
  const units = page.getByRole("dialog").getByLabel("Wyprodukowane opakowania");
  await expect(units).toBeVisible();
  await expect(units).not.toHaveAttribute("max", /.+/);
  await units.fill("9999");
  await expect(units).toHaveValue("9999");
});
