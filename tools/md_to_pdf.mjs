// tools/md_to_pdf.py가 만든 HTML을 A4 PDF로 찍는다. 표준 입력: 줄마다 "HTML 경로<TAB>PDF 경로". web/node_modules의 Playwright를 쓴다.
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(path.join(process.cwd(), "package.json"));
const { chromium } = require("playwright");
const jobs = fs.readFileSync(0, "utf8").split("\n").filter(Boolean).map((l) => l.split("\t"));
const browser = await chromium.launch({ channel: "chrome" }); // 설치된 Chrome을 쓴다(Playwright 전용 브라우저를 따로 받지 않음)
const page = await browser.newPage();
for (const [html, pdf] of jobs) {
  await page.goto(pathToFileURL(html).href);
  await page.waitForLoadState("networkidle");
  await page.pdf({ path: pdf, format: "A4", printBackground: true, margin: { top: "16mm", bottom: "16mm", left: "14mm", right: "14mm" } });
  console.log("PDF", pdf);
}
await browser.close();
