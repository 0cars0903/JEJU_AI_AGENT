import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export type CompareRow = { label: string; values: Record<string, string> };

export function CompareTable({ dongs, rows }: { dongs: string[]; rows: CompareRow[] }) {
  return (
    <div tabIndex={0} role="region" aria-label="동네 비교표" className="overflow-x-auto print:overflow-visible rounded-(--radius) border border-(--krds-border-gray-light)" data-testid="compare-table">
      <Table className="text-[length:var(--krds-fs-body-small)] print:table-fixed print:text-[9.5pt]">
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead className="sticky left-0 z-10 min-w-40 bg-muted font-bold text-foreground print:static print:h-auto print:min-w-0 print:whitespace-normal print:px-1.5">항목</TableHead>
            {dongs.map((d) => (
              <TableHead key={d} className="min-w-32 font-bold text-foreground print:h-auto print:min-w-0 print:whitespace-normal print:px-1.5">
                {d}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.label}>
              <TableHead scope="row" className="sticky left-0 z-10 h-auto bg-background font-semibold whitespace-normal text-foreground print:static print:px-1.5">
                {r.label}
              </TableHead>
              {dongs.map((d) => (
                <TableCell key={d} className="whitespace-normal print:px-1.5">
                  {r.values[d]}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
