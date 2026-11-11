import { expect, test } from "@playwright/test";

// 장면 점검용 캡처(SHOTS=경로 일 때만). 응답을 1.5초 늦춰 대기 표시·로딩 뼈대를 찍는다.
const OUT = process.env.SHOTS;
test.skip(!OUT, "SHOTS 경로가 있을 때만 실행");

test("장면 캡처", async ({ page }, info) => {
  const tag = info.project.name;
  await page.route("**/api/ask", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto("/");
  await expect(page.getByTestId("representative")).toBeVisible();
  await page.screenshot({ path: `${OUT}/${tag}-1-first.png`, fullPage: true });
  await page.getByTestId("question-input").fill("노형동 카페 몇 개야?");
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
