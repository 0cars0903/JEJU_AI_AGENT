import { queryOptions } from "@tanstack/react-query";
import { api } from "./api";

/** 자료가 실행 중에 바뀌지 않으므로 다시 받지 않는다. */
const FOREVER = { staleTime: Infinity, gcTime: Infinity };

export const queries = {
  meta: () => queryOptions({ queryKey: ["meta"], queryFn: api.meta, ...FOREVER }),
  map: () => queryOptions({ queryKey: ["map"], queryFn: api.map, ...FOREVER }),
  dong: (dong: string, category?: string) =>
    queryOptions({ queryKey: ["dong", dong, category ?? null], queryFn: () => api.dong(dong, category), ...FOREVER }),
  compare: (dongs: string[]) =>
    queryOptions({ queryKey: ["compare", dongs], queryFn: () => api.compare(dongs), enabled: dongs.length >= 2, ...FOREVER }),
  ask: (question: string, context: string[]) =>
    queryOptions({ queryKey: ["ask", question, context], queryFn: () => api.ask(question, context), ...FOREVER }),
};
