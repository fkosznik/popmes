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
  const customerName = "E2E · " + Date.now();
  await page.getByLabel("Nazwa", { exact: true }).fill(customerName);
  await page
    .getByLabel("Nazwa lokalizacji 1", { exact: true })
    .fill("Sklep Poznań");
  await page.getByLabel("Kod pocztowy 1").fill("61-001");
  await page.getByLabel("Miasto 1").fill("Poznań");
  await page.getByLabel("Ulica 1").fill("Testowa");
  await page.getByLabel("Numer domu 1").fill("1");
  await page
    .getByRole("button", { name: "Dodaj adres dostawy", exact: true })
    .click();
  await page
    .getByLabel("Nazwa lokalizacji 2", { exact: true })
    .fill("Sklep Gorzów");
  await page.getByLabel("Kod pocztowy 2").fill("66-400");
  await page.getByLabel("Miasto 2").fill("Gorzów");
  await page.getByLabel("Ulica 2").fill("Testowa");
  await page.getByLabel("Numer domu 2").fill("2");
  await page
    .getByRole("button", { name: "Zapisz zmiany", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByText(customerName)).toBeVisible();
  await page
    .getByRole("button", { name: "Zamówienia", exact: false })
    .first()
    .click();
  await page.getByRole("button", { name: "Nowe zamówienie" }).click();
  const clientOption = await page
    .getByRole("combobox", { name: "Klient", exact: true })
    .locator("option")
    .filter({ hasText: customerName })
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
  await page.getByRole("button", { name: "30 g", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Smak 1", exact: true })
    .selectOption({ label: "Słony karmel" });
  await page.getByLabel("Ilość 1").clear();
  await page.getByLabel("Ilość 1").pressSequentially("30");
  await expect(page.getByLabel("Ilość 1")).toHaveValue("30");
  await page.getByLabel("Ilość 1").fill("10");
  await page
    .getByRole("button", { name: "Zatwierdź do realizacji", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const drawer = page.getByRole("region", { name: "Szczegóły zamówienia" });
  await expect(drawer.getByText(/Testowa 2, 66-400 Gorzów/)).toBeVisible();
  await expect(
    drawer.getByRole("button", { name: "Zgłoś opakowania" }),
  ).toBeVisible();
  const number = await drawer.locator("h2").textContent();
  await page.getByRole("button", { name: "Zamknij szczegóły" }).click();
  await page.getByRole("button", { name: /^Produkcja/ }).click();
  const prod = page.locator(".task-card").filter({ hasText: number! });
  await prod.getByRole("button", { name: "Rozpocznij", exact: true }).click();
  await expect(prod.getByRole("button", { name: "Pauza" })).toBeVisible();
  await prod.getByRole("button", { name: "Zgłoś opakowania" }).click();
  await expect(
    page.getByLabel("Wyprodukowane opakowania", { exact: true }),
  ).toHaveValue("10");
  await page.getByLabel("Wyprodukowane opakowania", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: /^Wysyłka/ }).click();
  const pack = page.locator(".task-card").filter({ hasText: number! });
  await expect(pack.getByText("10 szt.")).toBeVisible();
  await expect(pack.getByText(/Testowa 2, 66-400 Gorzów/)).toBeVisible();
  await expect(pack.getByRole("button", { name: "Rozpocznij" })).toHaveCount(0);
  await expect(pack.getByRole("button", { name: "Wysłano" })).toBeDisabled();
  await expect(pack.getByText("Czeka na produkcję")).toBeVisible();
  await pack.getByRole("button", { name: "Więcej szczegółów" }).click();
  await expect(drawer.getByText(number!)).toBeVisible();
  await page.getByRole("button", { name: "Zamknij szczegóły" }).click();
  await page.getByRole("button", { name: /^Produkcja/ }).click();
  await prod.getByRole("button", { name: "Zgłoś opakowania" }).click();
  await page.getByLabel("Wyprodukowane opakowania", { exact: true }).fill("5");
  await page.getByRole("button", { name: "Zapisz wykonanie" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await page.getByRole("button", { name: /^Wysyłka/ }).click();
  await pack.getByRole("button", { name: "Wysłano" }).click();
  await expect(pack).toHaveCount(0);
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
  await page.getByRole("button", { name: /^Produkcja/ }).click();
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
  const address = page.getByRole("combobox", { name: /Adres dostawy/ });
  const addressId = await address.locator("option").nth(1).getAttribute("value");
  await address.selectOption(addressId!);
  await page.getByLabel("Termin gotowości").fill("2026-12-01T15:00");
  await page.getByRole("button", { name: "30 g", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Smak 1", exact: true })
    .selectOption({ label: "Słony karmel" });
  await page.getByRole("checkbox", { name: "Popcorn z logo" }).check();
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

test("menu pokazuje wersję z API", async ({ page }) => {
  await page.goto("/");
  await page
    .getByLabel("Login", { exact: true })
    .fill(process.env.POP_TEST_USER || "admin");
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(process.env.POP_TEST_PASSWORD || "Local-test-Only-925!");
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await expect(page.getByText("POPMES 0.1.2")).toBeVisible();
  await page.getByRole("button", { name: /Zamówienia/ }).click();
  await expect(
    page.getByRole("combobox", { name: "Status zamówienia" }).locator("option", {
      hasText: "W trakcie realizacji",
    }),
  ).toHaveCount(1);
  await expect(page.getByRole("button", { name: /Produkcja/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Wysyłka/ })).toBeVisible();
});

test("błąd pobrania wersji nie blokuje logowania", async ({ page }) => {
  await page.route("**/api/version/", (route) => route.abort());
  await page.goto("/");
  await page
    .getByLabel("Login", { exact: true })
    .fill(process.env.POP_TEST_USER || "admin");
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(process.env.POP_TEST_PASSWORD || "Local-test-Only-925!");
  await page.getByRole("button", { name: "Zaloguj się" }).click();
  await expect(page.getByRole("heading", { name: /Cześć/ })).toBeVisible();
  await expect(page.getByText(/^POPMES \d/)).toHaveCount(0);
});
