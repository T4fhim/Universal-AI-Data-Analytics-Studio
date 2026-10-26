import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ApiError } from './api/client.ts'
import { expireSession } from './api/queries.ts'
import './index.css'
import { DataProvider } from './workbench/data.tsx'
import { Workbench } from './workbench/Workbench.tsx'

// Server data is only refetched on demand (datasets are immutable once ingested), so a window
// refocus must not trigger requests against the preview rate budget. A 4xx is an answer, not a
// glitch, so it is not retried (a retried 429 would double the spend); only network errors and
// 5xx are, once. A 401 anywhere means the session ended: show sign-in and drop tenant data.
const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) queueMicrotask(() => expireSession(queryClient))
    },
  }),
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <DataProvider>
        <Workbench />
      </DataProvider>
    </QueryClientProvider>
  </StrictMode>,
)
