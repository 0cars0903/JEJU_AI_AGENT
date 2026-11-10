import path from "node:path";
import { expect, test } from "@playwright/test";
import { gold } from "./helpers";

// 제출 문서(docs/제출/build_docs.py)에 들어가는 캡처. 화면을 고치면 함께 갱신된다.
const OUT = path.resolve(__dirname, "../../docs/제출/화면");
const CLIP = { x: 0, y: 0, width: 1280, height: 1000 };

test("제출 문서 캡처", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "문서에는 데스크톱 화면만 넣는다");
  await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
  await expect(page.getByTestId("chart-survival").locator(".recharts-wrapper > svg")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT, "질문_답변.png"), fullPage: true, clip: CLIP });
  await page.goto("/diagnosis/");
  await expect(page.getByTestId("chart-visit").locator(".recharts-wrapper > svg")).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "동네진단.png"), fullPage: true, clip: CLIP });
});
