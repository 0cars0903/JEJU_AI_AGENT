import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";

export const metadata: Metadata = {
  title: "제주 상권 EDA",
  description: "제주빅데이터센터를 찾는 소상공인·예비창업자·중소기업의 상권 질문에 공공 자료로 계산한 답과 보고서를 드립니다.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#ffffff" };

// 표시 설정을 첫 그림 전에 적용해 글자 크기가 깜빡이지 않게 한다.
const applySettings = `try{var s=JSON.parse(localStorage.getItem("display-settings")||"{}");if(s.size)document.documentElement.style.fontSize=s.size+"%";if(s.contrast==="high")document.documentElement.dataset.contrast="high"}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: applySettings }} />
      </head>
      <body className="flex min-h-dvh flex-col antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-(--radius) focus:bg-background focus:p-3"
        >
          본문 바로가기
        </a>
        <Providers>
          <SiteHeader />
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[75rem] flex-1 px-4 py-6 outline-none md:px-6 md:py-10">
            {children}
          </main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
