export type Incident = { id: number; integration: string; error_code: string; title: string; status: 'open' | 'closed'; occurrence_count: number; first_event_at: string; last_event_at: string; created_at: string; updated_at: string; closed_at: string | null; resolution: string | null }
export type Event = { id: number; event_id: string; integration: string; status: 'success' | 'failure'; error_code: string | null; message: string; occurred_at: string; received_at: string }
export type Delivery = { id: number; event_id: string; status: 'pending' | 'running' | 'succeeded' | 'exhausted'; cycle: number; attempt_count: number; next_attempt_at: string | null; last_error: string | null }
export type Attempt = { id: number; delivery_id: number; cycle: number; attempt_number: number; started_at: string; finished_at: string; result: 'failed' | 'succeeded'; failure_reason: string | null }
export type ProcessingResult = { duplicate: boolean; action: string; event_id: string; incident: Incident | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } }) }
  catch { throw new Error('Sem conexão com a API. Verifique se ela está em execução.') }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = body.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: { msg: string }) => item.msg).join('; ') : 'Erro ao processar a solicitação.')
  }
  return response.json() as Promise<T>
}
const params = (value: Record<string, string | number | undefined>) => {
  const query = new URLSearchParams()
  Object.entries(value).forEach(([key, item]) => { if (item !== undefined && item !== '') query.set(key, String(item)) })
  return query.toString()
}
export const api = {
  counts: () => request<{ open: number; closed: number }>('/api/v1/incidents/counts'),
  incidents: (filters: { status?: string; integration?: string; error_code?: string; offset?: number }) =>
    request<Incident[]>('/api/v1/incidents?' + params({ ...filters, limit: 20 })),
  incident: (id: number) => request<Incident>('/api/v1/incidents/' + id),
  events: (id: number) => request<Event[]>('/api/v1/incidents/' + id + '/events'),
  deliveries: (id: number) => request<Delivery[]>('/api/v1/incidents/' + id + '/deliveries'),
  attempts: (id: number) => request<Attempt[]>('/api/v1/deliveries/' + id + '/attempts'),
  close: (id: number, resolution: string) => request<Incident>('/api/v1/incidents/' + id + '/close', {
    method: 'PATCH', body: JSON.stringify({ resolution }),
  }),
  reprocess: (id: number) => request<Delivery>('/api/v1/deliveries/' + id + '/reprocess', { method: 'POST' }),
  event: (event: { event_id: string; integration: string; status: 'failure' | 'success'; error_code?: string; message: string; occurred_at: string; simulated_failures: number }) =>
    request<ProcessingResult>('/api/v1/events', { method: 'POST', body: JSON.stringify(event) }),
}
