import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: process.env.POP_TEST_URL || "http://127.0.0.1:5173",
    headless: true,
    launchOptions: process.env.POP_CHROMIUM_PATH
      ? {
          executablePath: process.env.POP_CHROMIUM_PATH,
          args: [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-zygote",
            "--single-process",
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--disable-gpu",
          ],
        }
      : undefined,
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  reporter: "list",
});
