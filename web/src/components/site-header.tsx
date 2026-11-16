"use client";

/** 머리말(2026-11-13 사이드바 안 1): 서비스 이름·부제와 폰·태블릿의 메뉴(☰) 단추만 둔다.
 * 탭이 '질문하기' 하나뿐이던 메뉴, 상세 분석 바로 가기, 로그인은 사이드바로 옮겼다.
 * 높이 PC 64px·폰 56px. 서비스 이름은 기획서와 같은 이름(사용자 결정 11/13), 부제는 짧은 설명(PC만). KRDS 헤더의 '서비스 정체성(로고·슬로건)' 자리이며,
 * 공식 배너(정부 공식 누리집 표시)는 공식 서비스가 아니라 넣지 않는다. */
import Link from "next/link";
import { Menu } from "lucide-react";
import { useNav } from "@/components/nav-context";

export function SiteHeader() {
  const nav = useNav();
  return (
    <header className="sticky top-0 z-40 h-[56px] border-b border-(--krds-border-gray-light) bg-background print:hidden md:h-[64px]">
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
        <Link href="/" data-testid="brand" className="flex min-w-0 flex-col px-2 no-underline md:flex-row md:items-baseline md:gap-3">
          <span className="text-[15px] leading-tight font-bold text-(--krds-text-bolder) md:text-[19px]">제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent</span>
          <span data-testid="brand-sub" className="hidden truncate text-[14px] leading-tight text-(--krds-text-subtle) xl:inline">
            센터 PC에서 쓰는 상권 분석 보조
          </span>
        </Link>
      </div>
    </header>
  );
}
