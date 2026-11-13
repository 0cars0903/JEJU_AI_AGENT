"use client";

/** 데모 로그인(2026-11-13): 계정이 설정된 데모에서만 보인다. 로그인해야 Claude를 쓰는 기능(판단 과정 AI 설명·전문가 모드)이 켜진다. */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, getMe, login, logout } from "@/lib/api";

export function LoginForm({ onDone }: { onDone?: () => void }) {
  const qc = useQueryClient();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const m = useMutation({
    mutationFn: () => login(id.trim(), pw),
    onSuccess: () => {
      setPw("");
      qc.invalidateQueries();
      onDone?.();
    },
  });
  return (
    <form
      data-testid="login-form"
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim() && pw) m.mutate();
      }}
    >
      <label className="flex flex-col gap-1">
        <span>아이디</span>
        <input data-testid="login-id" value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" className="h-11 rounded-(--radius) border border-(--krds-border-gray) px-3" />
      </label>
      <label className="flex flex-col gap-1">
        <span>비밀번호</span>
        <input data-testid="login-pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" className="h-11 rounded-(--radius) border border-(--krds-border-gray) px-3" />
      </label>
      {m.isError && (
        <p data-testid="login-error" role="alert" className="text-(--krds-text-danger,#c0392b)">
          {m.error instanceof ApiError ? m.error.message : "로그인하지 못했어요."}
        </p>
      )}
      <Button type="submit" data-testid="login-submit" disabled={!id.trim() || !pw || m.isPending} className="self-start">
        {m.isPending ? "확인하는 중" : "로그인"}
      </Button>
    </form>
  );
}

/** 사이드바 접기 단추 아래 계정 자리(사용자 결정 2026-11-13). compact = 사이드바를 아이콘 폭으로 접었을 때(이름은 말풍선 Tip이 보인다).
 * 로그인 창은 단추 아래에 연다. 사이드바가 넘침을 잘라 내므로 화면 기준(fixed) 자리에 그린다. */
export function LoginButton({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe, retry: false, staleTime: 60_000 });
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const boxRef = useRef<HTMLDivElement>(null);
  const out = useMutation({ mutationFn: logout, onSuccess: () => qc.invalidateQueries() });
  // 로그인 창이 질문 칸·[묻기]를 덮으므로 바깥을 누르거나 Esc를 누르면 닫는다(UI 검토 2026-11-13)
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", down, true); // 지도처럼 전파를 막는 부품 위를 눌러도 닫히게 붙잡기 단계에서 듣는다
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  if (!me.data?.login_required) return null;
  if (me.data.logged_in)
    return (
      <div className={"flex items-center gap-2 " + (compact ? "flex-col" : "flex-wrap")} data-testid="login-state">
        <span className="flex items-center gap-1 text-(--krds-text-subtle)">
          <UserRound size={18} aria-hidden />
          {compact ? <span className="sr-only">{me.data.id} 로그인</span> : `${me.data.id} 로그인`}
        </span>
        <Button variant="outline" size="sm" data-testid="logout" onClick={() => out.mutate()} aria-label="로그아웃">
          <LogOut size={16} aria-hidden />
          {!compact && "로그아웃"}
        </Button>
      </div>
    );
  return (
    <div className="relative" ref={boxRef}>
      <Button
        variant="outline"
        size="sm"
        data-testid="login-open"
        aria-expanded={open}
        aria-label="로그인"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          setAt({ x: Math.max(8, Math.min(r.left, window.innerWidth - 296)), y: r.bottom + 8 });
          setOpen((v) => !v);
        }}
      >
        <LogIn size={16} aria-hidden />
        {!compact && "로그인"}
      </Button>
      {open && (
        <div style={{ left: at.x, top: at.y }} className="fixed z-[60] w-72 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-3 shadow-xl">
          <p className="mb-2 text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">로그인하면 AI 설명과 전문가 모드가 켜져요. 질문과 답은 로그인 없이도 쓸 수 있어요.</p>
          <LoginForm onDone={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}
