"use client";

/** 머리말(2026-11-13 사이드바 안 1): 서비스 이름과 폰·태블릿의 메뉴(☰) 단추만 둔다.
 * 탭이 '질문하기' 하나뿐이던 메뉴, 전문가 모드 바로 가기, 로그인은 사이드바로 옮겼다. */
import Link from "next/link";
import { Menu } from "lucide-react";
import { useNav } from "@/components/nav-context";

export function SiteHeader() {
  const nav = useNav();
  return (
    <header className="sticky top-0 z-40 h-[49px] border-b border-(--krds-border-gray-light) bg-background print:hidden">
      <div className="flex h-full w-full items-center gap-2 px-2 md:px-4">
        <button
          type="button"
          data-testid="nav-open"
          onClick={() => nav.setDrawer(true)}
          aria-label="사이드 메뉴 열기"
          aria-expanded={nav.drawer}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-(--radius) hover:bg-muted lg:hidden"
        >
          <Menu size={22} aria-hidden />
        </button>
        <Link href="/" className="px-2 text-[length:var(--krds-fs-heading-xsmall)] font-bold text-(--krds-text-bolder) no-underline hover:text-(--krds-text-bolder)">
          제주 상권 EDA
        </Link>
      </div>
    </header>
  );
}
