"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsAdapter } from "nuqs/adapters/next/app";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        // LLM이 들어간 질문은 되풀이해도 결과가 같거나 오래 걸리므로 한 번만 다시 시도한다.
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <NuqsAdapter>{children}</NuqsAdapter>
    </QueryClientProvider>
  );
}
