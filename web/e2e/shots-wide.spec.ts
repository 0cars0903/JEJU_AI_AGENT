import { expect, test } from "@playwright/test";
const OUT = process.env.SHOTS;
test.skip(!OUT, "SHOTS 경로가 있을 때만 실행");
for (const [w, h] of [[1920, 1080], [1440, 900]]) {
  test(`폭 ${w} 첫 화면·결과`, async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.setViewportSize({ width: w, height: h });
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/w${w}-home.png` });
    await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
    await page.getByTestId("ask-submit").click();
    await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1, { timeout: 10000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/w${w}-answer.png` });
  });
}
