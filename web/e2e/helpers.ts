import fs from "node:fs";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

export const gold = JSON.parse(fs.readFileSync(path.join(__dirname, "case-gold.json"), "utf-8"));
export const SHOTS = path.resolve(__dirname, "../../docs/평가/화면_web");

export async function shot(page: Page, name: string, projectName: string) {
  fs.mkdirSync(SHOTS, { recursive: true });
  // 차트 칸마다 실제 그림이 나온 뒤 찍는다. 고정 머리글이 겹치지 않게 맨 위로 올린다.
  const frames = page.locator('figure[role="img"]');
  for (let i = 0; i < (await frames.count()); i++) await expect(frames.nth(i).locator(".recharts-wrapper > svg")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1200); // 아이콘 애니메이션이 끝난 상태를 찍는다
  await page.screenshot({ path: path.join(SHOTS, `${projectName}_${name}.png`), fullPage: true });
}

/** 표시되는 글자에 기대 문구가 그대로 있는지 본다. */
export async function expectTexts(page: Page, texts: string[], absent: string[] = []) {
  const body = page.locator("main");
  for (const t of texts) await expect(body).toContainText(t);
  // 금지 문구는 답변 영역만 본다. 첫 화면 케이스 카드의 질문 글자와 구분하기 위해서다.
  for (const t of absent) await expect(page.getByTestId("answer")).not.toContainText(t);
}

export async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(over, "가로 스크롤이 없어야 한다").toBeLessThanOrEqual(0);
}

/** 휴대폰 화면에서는 뒤쪽 대표 질문이 접혀 있어 펼친다. 화면이 준비되기 전의 클릭은 무시될 수 있어 펼쳐질 때까지 다시 누른다. */
export async function showAllCases(page: Page) {
  const more = page.getByRole("button", { name: /대표 질문 \d+개 더 보기/ });
  await expect(page.getByTestId("cases")).toBeVisible(); // 첫 그림은 자리표시라 목록이 나온 뒤에 본다
  if (!(await more.isVisible())) return;
  await expect(async () => {
    if (await more.isVisible()) await more.click({ timeout: 1000 });
    await expect(more).toBeHidden({ timeout: 500 });
  }).toPass();
}

export async function openCase(page: Page, testCase: string) {
  await showAllCases(page);
  await page.getByTestId(`case-${testCase}`).click();
}
