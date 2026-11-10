import { cn } from "cn";

/** 카드 한 칸. 머리글이 있으면 그 아래 내용을 둔다. KRDS padding-card 토큰을 쓴다. */
export function Panel({ title, description, action, className, children, testId, breakable }: {
  title?: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
  testId?: string;
  /** 내용이 길어 인쇄할 때 쪽을 넘겨도 되는 칸 */
  breakable?: boolean;
}) {
  return (
    <section data-testid={testId} className={cn(!breakable && "print-avoid", "rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 md:p-6", className)}>
      {(title || action) && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            {title && <h3>{title}</h3>}
            {description && <p className="mt-0.5 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">{description}</p>}
          </div>
          {action && <div className="print:hidden">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
