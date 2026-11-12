"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useIconHover } from "@animateicons/react";
import { cn } from "cn";
import { MessageCircleIcon } from "@/components/icons";

const NAV = [
  { href: "/", label: "질문하기", Icon: MessageCircleIcon },
];

function NavItem({ href, label, Icon, active }: (typeof NAV)[number] & { active: boolean }) {
  const { ref, triggerProps } = useIconHover();
  return (
    <Link
      href={href}
      {...triggerProps}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-12 items-center gap-1.5 border-b-[3px] px-2 font-semibold whitespace-nowrap no-underline sm:px-3",
        "text-[length:var(--krds-fs-label-small)]",
        active
          ? "border-(--krds-border-primary) text-(--krds-text-primary) hover:text-(--krds-text-primary)"
          : "border-transparent text-(--krds-text-subtle) hover:bg-muted hover:text-(--krds-text-basic)",
      )}
    >
      <Icon ref={ref} size={20} aria-hidden />
      {label}
    </Link>
  );
}

export function SiteHeader() {
  const path = usePathname();
  return (
    <header className="border-b border-(--krds-border-gray-light) bg-background print:hidden md:sticky md:top-0 md:z-40">
      <div className="mx-auto flex w-full max-w-[100rem] flex-wrap items-center gap-x-6 px-4 md:px-6">
        <Link href="/" className="py-3 text-[length:var(--krds-fs-heading-xsmall)] font-bold text-(--krds-text-bolder) no-underline hover:text-(--krds-text-bolder)">
          제주 상권 EDA
        </Link>
        <nav aria-label="주요 메뉴" className="flex flex-wrap gap-x-1">
          {NAV.map((n) => (
            <NavItem key={n.href} {...n} active={n.href === "/" ? path === "/" : path.startsWith(n.href.slice(0, -1))} />
          ))}
        </nav>
      </div>
    </header>
  );
}
