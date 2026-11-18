"use client";

/** 왼쪽 사이드바(사용자 의견 → 안 1 결정, 2026-11-13).
 * KRDS 사이드 메뉴 지침: 이동용 메뉴, 계층 최대 2단계, role="navigation"·aria-current, 좁은 화면에서는 본문 옆에 두지 않는다.
 * - PC(1024px 이상): 본문 왼쪽에 고정. 펼침(240px) ↔ 아이콘 폭(64px) 접힘, Ctrl/Cmd+B.
 * - 폰·태블릿: 머리말 ☰로 여는 서랍. Esc·바깥 누름·메뉴 고르기로 닫히고, 열면 첫 항목에 초점, 닫으면 ☰로 초점을 돌려준다.
 * - 넣지 않음: 최근 질문 기록(공용 센터 PC, 기록을 남기지 않는 창 결정). */
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { RotateCcw, ChevronDown, ChevronsLeft, ChevronsRight, Code2, Download, ExternalLink, FlaskConical, House, Link2, ListChecks, Printer, Upload, X } from "lucide-react";
import { getExpertStatus, writeCenter } from "@/lib/api";
import { LoginButton } from "@/components/login";
import { Tip } from "@/components/tip";
import { useNav } from "@/components/nav-context";
import { copyText } from "@/features/ask/views";

// 기법 분석 13종(app/techniques.py EXAMPLES와 같은 문장). 누르면 그 예시 질문으로 답한다.
// 이름 옆에 쉬운 말을 함께 적는다(1차 사용자 도민, 이중 검토 040 요청 1). local = 지금 보던 동네로 바꿔 물을 수 있는 기법.
const TECH: { k: string; name: string; plain: string; q: string; local?: string }[] = [
  { k: "corr", name: "상관", plain: "같이 움직이는 정도", q: "43개 동네 방문과 매출의 상관 분석해줘" },
  { k: "cluster", name: "군집", plain: "비슷한 동네끼리 묶기", q: "43개 동네를 군집분석 해줘" },
  { k: "decomp", name: "시계열 분해", plain: "추세와 계절 나누기", q: "노형동 음식점 월 매출 시계열 분해해줘", local: "노형동" },
  { k: "regress", name: "회귀", plain: "매출에 미치는 영향", q: "동네별 매출에 방문과 가게 수가 미치는 영향 회귀분석해줘" },
  { k: "test", name: "두 집단 검정", plain: "차이가 우연인지", q: "노형동과 연동 음식점 매출이 통계적으로 차이 있어?" },
  { k: "dist", name: "분포", plain: "43개 동네 값의 흩어짐", q: "43개 동네 음식점 매출 분포 보여줘" },
  { k: "outlier", name: "이상치", plain: "튀는 달 찾기", q: "제주 전체 음식점 매출에서 튀는 달 찾아줘", local: "제주 전체" },
  { k: "change", name: "변화 분해", plain: "건수와 건당 금액", q: "노형동 음식점 매출 변화를 건수와 건당 금액으로 분해해줘", local: "노형동" },
  { k: "lq", name: "입지계수", plain: "이 동네에 몰린 업종", q: "노형동 업종별 입지계수 구해줘", local: "노형동" },
  { k: "surv", name: "생존분석", plain: "몇 년 버티는지", q: "노형동 음식점 생존 곡선 분석해줘", local: "노형동" },
  { k: "hhi", name: "업종 다양성", plain: "업종이 고르게 섞였는지", q: "노형동 업종 다양성 지수 알려줘", local: "노형동" },
  { k: "shift", name: "변이할당", plain: "성장 원인 나누기", q: "노형동 카드 매출 변이할당 분석해줘", local: "노형동" },
  { k: "sat", name: "포화도", plain: "가게가 넘치는지", q: "노형동 카페 포화도 알려줘", local: "노형동" },
];

function Item({ icon, label, onClick, href, current, compact, testId, extra }: {
  icon: React.ReactNode; label: string; onClick?: () => void; href?: string; current?: boolean; compact: boolean; testId: string; extra?: string;
}) {
  const cls =
    "flex min-h-11 w-full items-center gap-2 rounded-(--radius) px-3 text-left hover:bg-muted " +
    (current ? "bg-(--krds-surface-primary-subtler) font-semibold text-(--krds-text-primary)" : "text-(--krds-text-basic)") +
    (compact ? " justify-center px-0" : "");
  const body = (
    <>
      {icon}
      {compact ? <span className="sr-only">{label}</span> : <span className="flex-1">{label}{extra && <span className="ml-1 text-[length:var(--krds-fs-body-small)] font-normal text-(--krds-text-subtle)">{extra}</span>}</span>}
    </>
  );
  return (
    <li>
      <Tip on={compact} text={extra ? `${label} · ${extra}` : label}>
        {href ? (
          <a href={href} data-testid={testId} aria-current={current ? "page" : undefined} className={cls} onClick={onClick}>
            {body}
          </a>
        ) : (
          <button type="button" data-testid={testId} className={cls} onClick={onClick}>
            {body}
          </button>
        )}
      </Tip>
    </li>
  );
}

function Group({ title, compact, children }: { title: string; compact: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      {compact ? <hr className="mx-2 my-1 border-(--krds-border-gray-light)" /> : <p className="px-3 pt-2 text-[length:var(--krds-fs-body-small)] font-semibold text-(--krds-text-subtle)">{title}</p>}
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </div>
  );
}

function Menu({ compact, close }: { compact: boolean; close: () => void }) {
  const nav = useNav();
  const router = useRouter();
  const sp = useSearchParams();
  const home = !sp.get("q") && !sp.get("s");
  const st = useQuery({ queryKey: ["expert-status"], queryFn: getExpertStatus, staleTime: Infinity, retry: false });
  const [techOpen, setTechOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const method = (() => {
    try {
      return (JSON.parse(sp.get("s") ?? "{}") as { method?: string }).method;
    } catch {
      return undefined;
    }
  })();
  const ask = (slots: Record<string, unknown>, label: string) => {
    const p = new URLSearchParams();
    p.set("s", JSON.stringify(slots));
    p.set("l", label);
    router.push(`/?${p}`);
    close();
  };
  const jump = (id: string) => {
    close();
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const S = 20;
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-0.5">
        <Item
          compact={compact}
          testId="nav-home"
          icon={<House size={S} aria-hidden />}
          label="처음 화면"
          href="/"
          current={home}
          onClick={(e?: unknown) => {
            // [처음 화면]과 같은 동작: 센터 파일 열쇠를 지우고 이 답을 뒤로 가기 기록에서 뺀다(A7)
            (e as React.MouseEvent | undefined)?.preventDefault?.();
            writeCenter(null);
            window.location.replace("/");
          }}
        />
        <Item
          compact={compact}
          testId="nav-reset"
          icon={<RotateCcw size={S} aria-hidden />}
          label="새 상담 시작"
          onClick={() => {
            // 공용 센터 PC에서 방문자가 바뀔 때(이중 검토 040 요청 3): 센터 파일 열쇠·고른 동네·이 탭의 기록을 지우고 처음 화면으로
            writeCenter(null);
            try {
              localStorage.removeItem("jeju.dong");
              sessionStorage.clear();
            } catch {
              /* 무시 */
            }
            window.location.replace("/");
          }}
        />
      </ul>
      <Group title="묻기" compact={compact}>
        <Item compact={compact} testId="nav-picker" icon={<ListChecks size={S} aria-hidden />} label="입력 없이 골라서 묻기" onClick={() => { close(); nav.openPicker(); }} />
      </Group>
      <Group title="전문 분석" compact={compact}>
        <li>
          <Tip on={compact} text="통계 기법으로 보기">
          <button
            type="button"
            data-testid="nav-tech"
            aria-expanded={techOpen || Boolean(method)}
            onClick={() => (compact ? (nav.setCollapsed(false), setTechOpen(true)) : setTechOpen(!techOpen))}
            className={"flex min-h-11 w-full items-center gap-2 rounded-(--radius) px-3 text-left hover:bg-muted" + (compact ? " justify-center px-0" : "")}
          >
            <FlaskConical size={S} aria-hidden />
            {compact ? <span className="sr-only">통계 기법으로 보기</span> : <><span className="flex-1">통계 기법으로 보기</span><ChevronDown size={16} aria-hidden className={techOpen || method ? "rotate-180" : ""} /></>}
          </button>
          </Tip>
          {!compact && (techOpen || Boolean(method)) && (
            <ul className="ml-8 flex flex-col gap-0.5 border-l border-(--krds-border-gray-light) pl-2" data-testid="nav-tech-list">
              {TECH.map((t) => (
                <li key={t.k}>
                  <button
                    type="button"
                    data-testid={`nav-tech-${t.k}`}
                    aria-current={method === t.k ? "page" : undefined}
                    onClick={() => {
                      // 지금 보던 동네가 있으면 그 동네로 묻는다(이중 검토 040: 앞 질문 맥락 잇기)
                      const d = nav.answer.dong;
                      if (d && t.local) ask({ topic: "technique", method: t.k, space: [d] }, t.q.replace(t.local, d));
                      else ask({ topic: "technique", method: t.k }, t.q);
                    }}
                    className={"flex min-h-10 w-full items-center rounded-(--radius) px-2 text-left hover:bg-muted " + (method === t.k ? "font-semibold text-(--krds-text-primary)" : "")}
                  >
                    <span className="flex flex-col leading-tight">
                      <span>{t.name}</span>
                      <span className="text-[length:var(--krds-fs-body-small)] font-normal text-(--krds-text-subtle)">{t.plain}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </li>
        {(st.data?.available || st.data?.enabled) && (
          <Item
            compact={compact}
            testId="nav-expert"
            icon={<Code2 size={S} aria-hidden />}
            label="상세 분석"
            extra={st.data?.login_required ? "로그인 필요" : undefined}
            onClick={() => {
              close();
              requestAnimationFrame(() => {
                const el = document.getElementById("expert-area") as HTMLDetailsElement | null;
                if (!el) return;
                el.open = true;
                el.scrollIntoView({ behavior: "smooth", block: "start" });
                el.querySelector("summary")?.focus({ preventScroll: true });
              });
            }}
          />
        )}
      </Group>
      {nav.answer.hasAnswer && (
        <Group title="이 답" compact={compact}>
          <Item
            compact={compact}
            testId="nav-copy"
            icon={<Link2 size={S} aria-hidden />}
            label={copied ? "복사했어요" : "링크 복사"}
            onClick={async () => {
              if (await copyText(window.location.href)) {
                setCopied(true);
                setTimeout(() => setCopied(false), 2500);
              }
            }}
          />
          <Item compact={compact} testId="nav-new-tab" icon={<ExternalLink size={S} aria-hidden />} label="새 탭으로 열기" onClick={() => window.open(window.location.href, "_blank", "noopener")} />
          <Item compact={compact} testId="nav-print" icon={<Printer size={S} aria-hidden />} label="보고서 인쇄(PDF)" onClick={() => { close(); window.print(); }} />
          <Item compact={compact} testId="nav-downloads" icon={<Download size={S} aria-hidden />} label="자료 내려받기" onClick={() => jump("answer-downloads")} />
          {nav.answer.hasCenter && <Item compact={compact} testId="nav-center" icon={<Upload size={S} aria-hidden />} label="센터 자료 넣기" onClick={() => jump("request-center")} />}
        </Group>
      )}
    </div>
  );
}

export function AppSidebar() {
  const nav = useNav();
  const drawerRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  // 서랍: 열면 첫 항목에 초점, Esc로 닫기, 닫으면 연 단추로 초점을 돌려준다
  useEffect(() => {
    if (!nav.drawer) return;
    opener.current = document.activeElement as HTMLElement | null;
    requestAnimationFrame(() => drawerRef.current?.querySelector<HTMLElement>("a,button")?.focus());
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") nav.setDrawer(false);
      if (e.key === "Tab" && drawerRef.current) {
        // 서랍 안에서만 초점이 돌게 한다(모달 서랍)
        const f = Array.from(drawerRef.current.querySelectorAll<HTMLElement>("a,button,input")).filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      opener.current?.focus?.();
    };
  }, [nav.drawer, nav]);
  const c = nav.collapsed;
  return (
    <>
      {/* PC: 본문 왼쪽 고정 사이드바. 오른쪽 경계를 끌어 너비를 바꾼다(200~400px, 160px보다 좁히면 아이콘 폭으로 접힘) */}
      <nav
        aria-label="사이드 메뉴"
        data-testid="sidebar"
        style={c ? undefined : { width: nav.width }}
        className={"sticky top-[64px] hidden h-[calc(100dvh-64px)] shrink-0 flex-col overflow-y-auto border-r border-(--krds-border-gray-light) bg-background py-3 print:hidden lg:flex " + (c ? "w-16 px-1" : "px-2")}
      >
        <div className="flex flex-col gap-2">
          <Tip on={c} text="펼치기(Ctrl+B)">
            <button
              type="button"
              data-testid="nav-collapse"
              onClick={() => nav.setCollapsed(!c)}
              aria-label={c ? "사이드 메뉴 펼치기(Ctrl+B)" : "사이드 메뉴 접기(Ctrl+B)"}
              className={"flex min-h-9 w-full items-center rounded-(--radius) text-(--krds-text-subtle) hover:bg-muted " + (c ? "justify-center" : "justify-end px-2")}
            >
              {c ? <ChevronsRight size={18} aria-hidden /> : <ChevronsLeft size={18} aria-hidden />}
            </button>
          </Tip>
          {/* 계정 자리: 접기 단추 아래, 처음 화면 위(사용자 결정 11/13) */}
          <div data-testid="nav-account" className={c ? "flex justify-center" : "px-1"}>
            <Tip on={c} text="로그인·로그아웃">
              <LoginButton compact={c} />
            </Tip>
          </div>
          <Menu compact={c} close={() => undefined} />
        </div>
        <Resizer />
      </nav>
      {/* 폰·태블릿: 서랍 */}
      {nav.drawer && (
        <div className="fixed inset-0 z-50 lg:hidden print:hidden">
          <div aria-hidden className="absolute inset-0 bg-black/40" onClick={() => nav.setDrawer(false)} />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="사이드 메뉴"
            data-testid="drawer"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col justify-between overflow-y-auto bg-background p-3 shadow-2xl"
          >
            <nav aria-label="사이드 메뉴" className="flex flex-col gap-2">
              <button type="button" data-testid="drawer-close" onClick={() => nav.setDrawer(false)} className="flex min-h-11 items-center gap-1 self-end rounded-(--radius) px-3 hover:bg-muted">
                <X size={18} aria-hidden /> 닫기
              </button>
              <div data-testid="nav-account" className="px-1">
                <LoginButton />
              </div>
              <Menu compact={false} close={() => nav.setDrawer(false)} />
            </nav>
          </div>
        </div>
      )}
    </>
  );
}

/** 너비 조절 손잡이: 끌기·두 번 누르기(240px로)·키보드 ←/→(16px). 너비는 저장하지 않는다. */
function Resizer() {
  const nav = useNav();
  const MIN = 200, MAX = 400, SNAP = 160, BASE = 240;
  const drag = useRef<number | null>(null);
  const set = (w: number) => {
    if (w < SNAP) return nav.setCollapsed(true);
    nav.setCollapsed(false);
    nav.setWidth(Math.max(MIN, Math.min(MAX, Math.round(w))));
  };
  const now = nav.collapsed ? 64 : nav.width;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="사이드 메뉴 너비 조절(←/→, 두 번 누르면 기본 너비)"
      aria-valuemin={MIN}
      aria-valuemax={MAX}
      aria-valuenow={now}
      tabIndex={0}
      data-testid="nav-resize"
      className="absolute inset-y-0 right-0 w-1.5 cursor-col-resize hover:bg-(--krds-border-primary) focus-visible:bg-(--krds-border-primary) focus-visible:outline-none"
      onPointerDown={(e) => {
        drag.current = (e.currentTarget.parentElement?.getBoundingClientRect().left ?? 0);
        e.currentTarget.setPointerCapture(e.pointerId);
        e.preventDefault();
      }}
      onPointerMove={(e) => {
        if (drag.current !== null) set(e.clientX - drag.current);
      }}
      onPointerUp={(e) => {
        drag.current = null;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }}
      onDoubleClick={() => {
        nav.setCollapsed(false);
        nav.setWidth(BASE);
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") { e.preventDefault(); set(now - 16 < MIN ? SNAP - 1 : now - 16); }
        if (e.key === "ArrowRight") { e.preventDefault(); set(nav.collapsed ? MIN : now + 16); }
      }}
    />
  );
}
