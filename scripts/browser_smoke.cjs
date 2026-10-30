/* Optional real-browser check: npm install --prefix .local/browser-tests playwright */
const { chromium } = require("../.local/browser-tests/node_modules/playwright");
const { mkdirSync } = require("node:fs");
const { join } = require("node:path");
const { execFileSync } = require("node:child_process");
const assert = require("node:assert/strict");
const baseURL = process.env.CINEPHILE_TEST_URL || "http://127.0.0.1:8000";

(async () => {
  const root = join(__dirname, "..");
  const email = `qa-${Date.now()}@example.com`;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
    deviceScaleFactor: 1,
  });
  const errors = [];
  const failedImages = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (
      response.request().resourceType() === "image" &&
      response.status() >= 400
    )
      failedImages.push(response.url());
  });
  mkdirSync(join(root, ".local", "screenshots"), { recursive: true });
  try {
    await page.goto(baseURL);
    await page.waitForSelector(".movie-card");
    assert.equal(await page.locator(".movie-card").count(), 20);
    await page
      .locator(".poster")
      .first()
      .evaluate((img) => img.decode().catch(() => {}));
    await page.screenshot({
      path: join(root, ".local", "screenshots", "desktop.png"),
      fullPage: true,
    });
    await page.locator("#account-button").click();
    await page.locator("#register-tab").click();
    await page.locator("#auth-name").fill("Ciné Tester");
    await page.locator("#auth-email").fill(email);
    await page.locator("#auth-password").fill("Browser-test-password-2026");
    await page.locator("#auth-submit").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#account-label").textContent === "Ciné Tester",
    );
    await page.reload();
    await page.waitForSelector(".movie-card");
    assert.equal(
      await page.locator("#account-label").textContent(),
      "Ciné Tester",
    );
    await page.locator("#search-input").fill("Toy Story");
    await page.waitForFunction(
      () =>
        document.querySelectorAll(".movie-card").length === 1 &&
        document.querySelector(".movie-title").textContent === "Toy Story",
    );
    await page.locator(".poster-button").click();
    await page.waitForSelector("#review-form");
    await page
      .locator("#review-content")
      .fill("Một bộ phim đáng yêu. <script>window.qaXss = true</script>");
    await page.locator("#review-spoiler").check();
    await page.locator("#review-submit").click();
    await page.waitForSelector(".review-item");
    assert.equal(await page.locator(".review-text").isVisible(), false);
    await page.locator(".spoiler-summary").click();
    assert.match(await page.locator(".review-text").textContent(), /<script>/);
    assert.equal(await page.evaluate(() => window.qaXss), undefined);
    await page
      .locator("#review-content")
      .fill("Xem lại vẫn thấy rất vui, tình bạn thật đẹp.");
    await page.locator("#review-rating").selectOption("9");
    await page.locator("#review-submit").click();
    await page.waitForFunction(() =>
      document
        .querySelector(".review-score-badge")
        ?.textContent.includes("9/10"),
    );
    assert.equal(await page.locator(".review-item").count(), 1);
    await page.locator("#detail-save").click();
    await page.waitForFunction(() =>
      document.querySelector("#detail-save")?.textContent.includes("Đã lưu"),
    );
    await page.locator("#detail-watched").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#detail-watched")
        ?.textContent.includes("Đánh dấu chưa xem"),
    );
    await page.locator('[data-close="movie-dialog"]').click();
    await page.locator("#watchlist-nav").click();
    await page.waitForSelector(".movie-card");
    assert.equal(await page.locator(".movie-card").count(), 1);
    assert.equal(await page.locator(".watched-badge").textContent(), "Đã xem");
    await page.locator("#chat-fab").click();
    await page.waitForFunction(
      () =>
        !document
          .querySelector("#provider-status")
          .textContent.includes("Đang kiểm tra"),
    );
    await page.locator("#chat-provider").selectOption("rules");
    await page.locator("#chat-input").fill("Phim hài dưới 2 tiếng");
    await page.locator("#chat-send").click();
    await page.waitForSelector(".chat-mode-note");
    const chatTitles = await page
      .locator(".chat-result strong")
      .allTextContents();
    assert(!chatTitles.some((title) => title.includes("Toy Story")));
    assert((await page.locator(".chat-result").count()) > 0);
    await page.locator("#chat-provider").selectOption("ollama");
    await page.locator("#chat-input").fill("Hoạt hình dưới 2 tiếng");
    const qwenRequest = page.waitForRequest(
      (request) =>
        request.url().endsWith("/api/chat") && request.method() === "POST",
    );
    await page.locator("#chat-send").click();
    assert.equal((await qwenRequest).postDataJSON().provider, "ollama");
    await page.waitForSelector(".chat-mode-note", { timeout: 150000 });
    assert.match(
      await page.locator(".chat-mode-note").textContent(),
      /Qwen local/,
    );
    assert.equal(await page.locator("#chat-provider").inputValue(), "ollama");
    await page.screenshot({
      path: join(root, ".local", "screenshots", "model-selector.png"),
    });
    await page.locator("#chat-close").click();
    await page.locator("#explore-nav").click();
    await page.locator("#reset-filters").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".movie-card").length === 20,
    );
    await page.locator("#next-page").click();
    await page.waitForFunction(
      () => document.querySelector("#page-label").textContent === "2 / 2",
    );
    assert.equal(await page.locator(".movie-card").count(), 4);
    await page.locator("#prev-page").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".movie-card").length === 20,
    );
    await page.locator('[data-genre="16"]').click();
    await page.waitForFunction(() =>
      document
        .querySelector("#results-count")
        .textContent.includes("6 bộ phim"),
    );
    await page.locator("#reset-filters").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".movie-card").length === 20,
    );
    await page.setViewportSize({ width: 320, height: 740 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#toast").waitFor({ state: "hidden" });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: join(root, ".local", "screenshots", "mobile.png"),
      fullPage: true,
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.locator(".poster-button").first().click();
    await page.waitForSelector("#detail-title");
    assert.equal(
      await page
        .locator("#movie-dialog")
        .evaluate((el) => el.scrollWidth > el.clientWidth),
      false,
    );
    await page.screenshot({
      path: join(root, ".local", "screenshots", "mobile-detail.png"),
    });
    await page.locator('[data-close="movie-dialog"]').click();
    await page.locator("#account-button").click();
    await page.locator("#logout-button").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#account-label").textContent === "Đăng nhập",
    );
    const docsPage = await browser.newPage();
    docsPage.on("pageerror", (error) => errors.push(error.message));
    await docsPage.goto(baseURL + "/docs");
    await docsPage.waitForSelector(".swagger-ui .opblock");
    await docsPage.close();
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify(
        {
          result: "passed",
          checks:
            "SQLite auth/review/watchlist, model selector, local Ollama request/fallback, spoiler/XSS, pagination, responsive layout, Swagger docs",
          failedImages,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
    // Delete only the unique account created by this check; child data cascades.
    const python =
      process.platform === "win32"
        ? join(root, ".venv", "Scripts", "python.exe")
        : join(root, ".venv", "bin", "python");
    execFileSync(
      python,
      [
        "-c",
        "import sys; from sqlalchemy import delete; from backend.db import SessionLocal; from backend.models import User; db=SessionLocal(); db.execute(delete(User).where(User.email==sys.argv[1])); db.commit(); db.close()",
        email,
      ],
      { cwd: root },
    );
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
