import { expect, test } from "@playwright/test";

// 장면 점검용 캡처(SHOTS=경로 일 때만). 응답을 1.5초 늦춰 대기 표시·로딩 뼈대를 찍는다.
const OUT = process.env.SHOTS;
test.skip(!OUT, "SHOTS 경로가 있을 때만 실행");

test("장면 캡처", async ({ page }, info) => {
  const tag = info.project.name;
  await page.route("**/api/ask{,/stream}", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto("/");
  await expect(page.getByTestId("representative")).toBeVisible();
  await page.screenshot({ path: `${OUT}/${tag}-1-first.png`, fullPage: true });
  await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
  await page.getByTestId("ask-submit").click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}/${tag}-2-waiting.png`, fullPage: true });
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1, { timeout: 10000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${tag}-3-answer.png`, fullPage: true });
  await page.getByTestId("understood-change").click();
  await page.screenshot({ path: `${OUT}/${tag}-4-picker.png`, fullPage: true });
  await page.getByTestId("question-input").fill("카페 몇 개야?");
  await page.getByTestId("ask-submit").click();
  await expect(page.getByTestId("choose-notice")).toBeVisible({ timeout: 10000 });
  await page.screenshot({ path: `${OUT}/${tag}-5-choose.png`, fullPage: true });
});

test("v3 장면 캡처: 시장 추이·인쇄 보고서", async ({ page }, info) => {
  const tag = info.project.name;
  await page.goto("/");
  await page.getByTestId("open-picker").click();
  const picker = page.getByTestId("step-picker");
  await picker.getByTestId("topic-market").click();
  await picker.getByTestId("target-음식점").click();
  await page.screenshot({ path: `${OUT}/${tag}-6-picker-market.png`, fullPage: true });
  await picker.getByTestId("picker-submit").click();
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1, { timeout: 10000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${tag}-7-market.png`, fullPage: true });
  await page.emulateMedia({ media: "print" });
  await page.screenshot({ path: `${OUT}/${tag}-8-report-print.png`, fullPage: true });
});

test("v3 장면 캡처: F9 센터 CSV 넣기", async ({ page }, info) => {
  const tag = info.project.name;
  const raw = require("path").resolve(__dirname, "../../data/raw");
  const file = require("fs").readdirSync(raw).find((f: string) => f.includes("주제1") && f.endsWith("_21.csv"));
  await page.goto("/");
  await page.getByTestId("question-input").fill("노형동 카페 매출은?");
  await page.getByTestId("ask-submit").click();
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1, { timeout: 10000 });
  const card = page.getByTestId("request-center");
  await card.getByTestId("center-file").setInputFiles(require("path").join(raw, file));
  await expect(card.getByTestId("center-meta")).toBeVisible({ timeout: 30000 });
  await card.screenshot({ path: `${OUT}/${tag}-9-center-card.png` });
  await card.getByTestId("center-use").click();
  await expect(page.getByTestId("block-facts")).toContainText("이용자 불러옴", { timeout: 15000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${tag}-10-center-answer.png`, fullPage: true });
});

test("역설계 적용 캡처: 첫 화면·결과 지도", async ({ page }, info) => {
  const tag = info.project.name;
  await page.goto("/");
  await page.getByTestId("home-dong").selectOption("노형동"); // 숫자 카드는 동네를 고른 뒤에 나온다
  await expect(page.getByTestId("home-card-visit")).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${tag}-11-home.png`, fullPage: true });
  await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
  await page.getByTestId("ask-submit").click();
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1, { timeout: 10000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/${tag}-12-diagnose.png`, fullPage: true });
});
