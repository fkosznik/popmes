import { test, expect } from "@playwright/test";

test("sprzedaż → częściowa produkcja → pakowanie → wydanie", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page
    .getByLabel("Login", { exact: true })
    .fill(process.env.POP_TEST_USER || "admin");
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(process.env.POP_TEST_PASSWORD || "Local-test-Only-925!");
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await expect(page.getByRole("heading", { name: /Cześć/ })).toBeVisible();
  await expect(page.locator(".metrics")).toBeVisible();
  await page.screenshot({ path: "/tmp/popmes-dashboard.png", fullPage: true });
  await page.getByRole("button", { name: "Klienci", exact: true }).click();
  await page.getByRole("button", { name: "Dodaj klienta" }).click();
  await page.getByLabel("Nazwa", { exact: true }).fill("E2E · " + Date.now());
  await page
    .getByRole("button", { name: "Dodaj adres dostawy", exact: true })
    .click();
  await page
    .getByLabel("Nazwa lokalizacji 1", { exact: true })
    .fill("Sklep Poznań");
  await page
    .getByLabel("Adres dostawy 1", { exact: true })
    .fill("Testowa 1, Poznań");
  await page
    .getByRole("button", { name: "Dodaj adres dostawy", exact: true })
    .click();
  await page
    .getByLabel("Nazwa lokalizacji 2", { exact: true })
    .fill("Sklep Gorzów");
  await page
    .getByLabel("Adres dostawy 2", { exact: true })
    .fill("Testowa 2, Gorzów");
  await page
    .getByRole("button", { name: "Zapisz zmiany", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page
    .getByRole("button", { name: "Zamówienia", exact: false })
    .first()
    .click();
  await page.getByRole("button", { name: "Nowe zamówienie" }).click();
  const clientOption = await page
    .getByRole("combobox", { name: "Klient", exact: true })
    .locator("option")
    .filter({ hasText: "E2E ·" })
    .last()
    .getAttribute("value");
  await page
    .getByRole("combobox", { name: "Klient", exact: true })
    .selectOption(clientOption!);
  await page.getByLabel("Sposób odbioru").selectOption("courier");
  const address = page.getByRole("combobox", { name: /Adres dostawy/ });
  const addressId = await address
    .locator("option")
    .filter({ hasText: "Sklep Gorzów" })
    .getAttribute("value");
  await address.selectOption(addressId!);
  await page.getByLabel("Termin gotowości").fill("2026-12-01T15:00");
  const option = await page
    .getByRole("combobox", { name: "Produkt 1", exact: true })
    .locator("option")
    .filter({ hasText: /Słony karmel\s+·\s+30 g/ })
    .first()
    .getAttribute("value");
  await page
    .getByRole("combobox", { name: "Produkt 1", exact: true })
    .selectOption(option!);
  await page.getByLabel("Ilość 1").clear();
  await page.getByLabel("Ilość 1").pressSequentially("30");
  await expect(page.getByLabel("Ilość 1")).toHaveValue("30");
  await page.getByLabel("Ilość 1").fill("10");
  await page
    .getByRole("button", { name: "Zatwierdź do realizacji", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const drawer = page.getByRole("region", { name: "Szczegóły zamówienia" });
  await expect(drawer.getByText(/Testowa 2, Gorzów/)).toBeVisible();
  const number = await drawer.locator("h2").textContent();
  await page.getByRole("button", { name: "Zamknij szczegóły" }).click();
  await page.getByRole("button", { name: "Produkcja", exact: true }).click();
  const prod = page.locator(".task-card").filter({ hasText: number! });
  await prod.getByRole("button", { name: "Rozpocznij", exact: true }).click();
  await expect(prod.getByRole("button", { name: "Pauza" })).toBeVisible();
  await prod.getByRole("button", { name: "Zgłoś produkcję" }).click();
  await expect(
    page.getByLabel("Gotowy popcorn (kg)", { exact: true }),
  ).toHaveValue("0.3");
  await expect(
    page.getByLabel("Odpad produkcyjny (kg)", { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Gotowy popcorn (kg)", { exact: true }).fill("0.150");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: "Pakowanie", exact: true }).click();
  const pack = page.locator(".task-card").filter({ hasText: number! });
  await pack.getByRole("button", { name: "Zgłoś pakowanie" }).click();
  await page.getByLabel("Dodatkowe zapakowane sztuki").fill("5");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(
    pack.getByText("Oczekiwanie na popcorn", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Produkcja", exact: true }).click();
  await prod.getByRole("button", { name: "Zgłoś produkcję" }).click();
  await page.getByLabel("Gotowy popcorn (kg)", { exact: true }).fill("0.150");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: "Pakowanie", exact: true }).click();
  await pack.getByRole("button", { name: "Zgłoś pakowanie" }).click();
  await page.getByLabel("Dodatkowe zapakowane sztuki").fill("5");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page
    .getByRole("button", { name: "Zamówienia", exact: false })
    .first()
    .click();
  await page.getByRole("row").filter({ hasText: number! }).click();
  await expect(drawer.getByText("Zrealizowane", { exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "Oznacz jako wydane" }).click();
  await expect(drawer.getByText("Wydane", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  await page.getByRole("button", { name: "Zamknij szczegóły" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Otwórz menu" }).click();
  await page.getByRole("button", { name: "Produkcja", exact: true }).click();
  await page.screenshot({
    path: "/tmp/popmes-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("grafika przy pozycji z logo", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Login", { exact: true })
    .fill(process.env.POP_TEST_USER || "admin");
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(process.env.POP_TEST_PASSWORD || "Local-test-Only-925!");
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await page
    .getByRole("button", { name: "Nowe zamówienie", exact: true })
    .click();
  const customer = page.getByRole("combobox", { name: "Klient", exact: true });
  const cid = await customer
    .locator("option")
    .filter({ hasText: "E2E ·" })
    .last()
    .getAttribute("value");
  await customer.selectOption(cid!);
  await page.getByLabel("Termin gotowości").fill("2026-12-01T15:00");
  const product = page.getByRole("combobox", {
    name: "Produkt 1",
    exact: true,
  });
  const vid = await product
    .locator("option")
    .filter({ hasText: /z logo/ })
    .first()
    .getAttribute("value");
  await product.selectOption(vid!);
  await page.getByLabel("Ilość 1").fill("10");
  const file = page.locator('input[type="file"][name="label_0"]');
  await expect(file).toBeVisible();
  await file.setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await page
    .getByRole("button", { name: "Zatwierdź do realizacji", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const drawer = page.getByRole("region", { name: "Szczegóły zamówienia" });
  await expect(drawer.getByText(/logo.png/).first()).toBeVisible();
});
