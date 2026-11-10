"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 입력이 잘못된 요청과 LLM 질문은 되풀이해도 결과가 같거나 오래 걸리므로 다시 시도하지 않는다.
            retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <NuqsAdapter>{children}</NuqsAdapter>
    </QueryClientProvider>
  );
}
