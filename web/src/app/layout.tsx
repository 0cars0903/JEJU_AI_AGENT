import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "제주 상권 EDA",
  description: "제주빅데이터센터를 찾는 소상공인·예비창업자·중소기업의 상권 질문에 공공 자료로 계산한 답과 보고서를 드립니다.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#ffffff" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body className="flex min-h-dvh flex-col antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-(--radius) focus:bg-background focus:p-3"
        >
          본문 바로가기
        </a>
        <Providers>
          <SiteHeader />
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[100rem] flex-1 px-4 py-4 outline-none md:px-6 md:py-4">
            {children}
          </main>
          {/* 문서 23 8절(사용자 결정): AI 고지는 다른 서비스처럼 메인 페이지 맨 아래 작은 글씨로 둔다. 인공지능기본법 제31조 사전 고지. */}
          <footer data-testid="ai-notice" className="mx-auto w-full max-w-[100rem] px-4 pt-2 pb-4 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle) print:hidden md:px-6">
            이 서비스는 AI 모델로 질문을 해석하고, 판단 과정의 설명 문장 일부를 AI가 씁니다. 답의 숫자는 공공 자료로 프로그램이 계산한 값입니다. 중요한 결정 전에는 원자료와 전문가 의견을 함께 확인해 주세요.
          </footer>
        </Providers>
      </body>
    </html>
  );
}
