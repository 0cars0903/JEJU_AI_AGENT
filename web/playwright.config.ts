import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const PORT = 8611;
const ROOT = path.resolve(__dirname, "..");

// 운영과 같은 정적 빌드를 FastAPI로 띄워 시험한다. 기본은 LLM 없는 경로이고, LLM_BACKEND로 바꿀 수 있다. 수치 문장은 경로와 무관하게 같다.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  // Claude 경로는 답변에 4.6~11.7초가 걸린다(2026-11-07 실측). 기본 대기 5초로는 답변 전에 실패한다.
  ...(process.env.LLM_BACKEND === "claude" ? { timeout: 90_000, expect: { timeout: 30_000 } } : {}),
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${PORT}`, trace: "retain-on-failure", screenshot: "only-on-failure", locale: "ko-KR", video: process.env.RECORD ? "on" : "off" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome", viewport: { width: 1280, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome" } },
  ],
  webServer: {
    command: `.venv/bin/python -m uvicorn app.api:app --port ${PORT}`,
    cwd: ROOT,
    env: { LLM_BACKEND: process.env.LLM_BACKEND ?? "rule", PYTHONWARNINGS: "ignore" },
    url: `http://localhost:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
