import { BADGE_NOTES } from "@/lib/content";

export function BadgeRow({ badges }: { badges: Record<string, string> }) {
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="badges">
      {Object.entries(badges).map(([k, v]) => (
        <div key={k} className="print-avoid rounded-(--radius) border border-(--krds-border-gray-light) bg-muted p-3">
          <dt className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">{k}</dt>
          <dd className="my-0.5 font-bold text-(--krds-text-bolder)">{v}</dd>
          <dd className="text-[length:var(--krds-fs-body-xsmall)] text-(--krds-text-subtle)">{BADGE_NOTES[k]}</dd>
        </div>
      ))}
    </dl>
  );
}
