import { useCallback, useEffect, useState } from 'react'
import { api, type Attempt, type Delivery, type Event, type Incident } from './api'
import './style.css'

const when = (value: string | null) => value ? new Date(value).toLocaleString('pt-BR') : '—'
const stateName: Record<string, string> = { open: 'Aberto', closed: 'Encerrado', pending: 'Pendente', running: 'Em execução', succeeded: 'Concluída', exhausted: 'Esgotada', failed: 'Falhou' }

export default function App() {
  const [counts, setCounts] = useState({ open: 0, closed: 0 })
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [selected, setSelected] = useState<Incident | null>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [attempts, setAttempts] = useState<Record<number, Attempt[]>>({})
  const [status, setStatus] = useState('')
  const [integration, setIntegration] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const [offset, setOffset] = useState(0)
  const [resolution, setResolution] = useState('')
  const [simulatedFailures, setSimulatedFailures] = useState(3)
  const [lastDemo, setLastDemo] = useState<{ event_id: string; integration: string; error_code: string; message: string; occurred_at: string; simulated_failures: number } | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [nextCounts, nextIncidents] = await Promise.all([
        api.counts(), api.incidents({ status, integration, error_code: errorCode, offset }),
      ])
      setCounts(nextCounts); setIncidents(nextIncidents); setError('')
    } catch (cause) { setError((cause as Error).message) }
    finally { setLoading(false) }
  }, [status, integration, errorCode, offset])

  const openIncident = useCallback(async (id: number) => {
    try {
      const [incident, timeline, deliveryList] = await Promise.all([
        api.incident(id), api.events(id), api.deliveries(id),
      ])
      const histories = await Promise.all(deliveryList.map(item => api.attempts(item.id)))
      setSelected(incident); setEvents(timeline); setDeliveries(deliveryList)
      setAttempts(Object.fromEntries(deliveryList.map((item, index) => [item.id, histories[index]])))
      setError('')
    } catch (cause) { setError((cause as Error).message) }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const perform = async (action: () => Promise<void>, success: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await action(); setNotice(success); await refresh() }
    catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }

  const demoEvent = (index: number, seed: string, occurredAt: string) => ({
    event_id: seed + '-' + index, integration: 'demo-crm', status: 'failure' as const,
    error_code: 'DEMO_TIMEOUT', message: 'Destino fictício indisponível.',
    occurred_at: occurredAt, simulated_failures: simulatedFailures,
  })

  return <div className="shell">
    <header><div><span className="eyebrow">AMBIENTE DE DEMONSTRAÇÃO</span><h1>Integration Incident Monitor</h1><p>Falhas de integração, incidentes e entregas simuladas em um só lugar.</p></div><button onClick={() => void refresh()} disabled={loading}>Atualizar</button></header>
    {error && <div className="banner error" role="alert">{error}</div>}
    {notice && <div className="banner success" role="status">{notice}</div>}
    <section className="stats"><article><span>Incidentes abertos</span><strong>{counts.open}</strong></article><article><span>Incidentes encerrados</span><strong>{counts.closed}</strong></article></section>
    <main>
      <section className="card list"><h2>Incidentes</h2><div className="filters"><label>Status<select value={status} onChange={e => { setStatus(e.target.value); setOffset(0) }}><option value="">Todos</option><option value="open">Abertos</option><option value="closed">Encerrados</option></select></label><label>Integração<input value={integration} onChange={e => { setIntegration(e.target.value); setOffset(0) }} placeholder="Ex.: demo-crm" /></label><label>Código de erro<input value={errorCode} onChange={e => { setErrorCode(e.target.value); setOffset(0) }} placeholder="Ex.: DEMO_TIMEOUT" /></label></div>
        {loading ? <p>Carregando incidentes…</p> : incidents.length === 0 ? <p className="empty">Nenhum incidente encontrado. Gere três falhas na demonstração.</p> : <div className="incident-list">{incidents.map(item => <button className={'incident ' + (selected?.id === item.id ? 'active' : '')} key={item.id} onClick={() => void openIncident(item.id)}><span><strong>#{item.id} · {item.integration}</strong><small>{item.error_code} · {item.occurrence_count} falhas</small></span><span className={'badge ' + item.status}>{stateName[item.status]}</span></button>)}</div>}
        <div className="pager"><button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>Anterior</button><span>Página {offset / 20 + 1}</span><button disabled={incidents.length < 20 || loading} onClick={() => setOffset(offset + 20)}>Próxima</button></div>
      </section>
      <section className="card detail"><h2>Detalhes</h2>{selected ? <><div className="detail-head"><div><h3>#{selected.id} · {selected.title}</h3><p>Primeira falha: {when(selected.first_event_at)}<br/>Última falha: {when(selected.last_event_at)}</p></div><span className={'badge ' + selected.status}>{stateName[selected.status]}</span></div><button className="text-button" onClick={() => void openIncident(selected.id)}>Atualizar detalhes</button><h3>Linha do tempo</h3>{events.length === 0 ? <p className="empty">Nenhum evento.</p> : <ol className="timeline">{events.map(item => <li key={item.id}><strong>{when(item.occurred_at)}</strong><span>{item.event_id} · {item.message}</span></li>)}</ol>}<h3>Entregas e tentativas</h3>{deliveries.length === 0 ? <p className="empty">Nenhuma entrega.</p> : deliveries.map(delivery => <div className="delivery" key={delivery.id}><div className="delivery-title"><strong>{delivery.event_id}</strong><span className={'badge ' + delivery.status}>{stateName[delivery.status]}</span></div><small>Ciclo {delivery.cycle} · {delivery.attempt_count} tentativas {delivery.next_attempt_at && '· próxima: ' + when(delivery.next_attempt_at)}</small>{delivery.last_error && <p className="error-text">{delivery.last_error}</p>}<ul>{attempts[delivery.id]?.map(attempt => <li key={attempt.id}>#{attempt.attempt_number} · {when(attempt.started_at)} · {stateName[attempt.result]}{attempt.failure_reason && ' — ' + attempt.failure_reason}</li>)}</ul>{(delivery.status === 'exhausted' || delivery.status === 'pending') && <button disabled={busy} onClick={() => void perform(async () => { await api.reprocess(delivery.id); await openIncident(selected.id) }, 'Entrega reenfileirada para o destino fictício.')}>Reprocessar</button>}</div>)}{selected.status === 'open' ? <form onSubmit={e => { e.preventDefault(); void perform(async () => { await api.close(selected.id, resolution); setResolution(''); await openIncident(selected.id) }, 'Incidente encerrado.') }}><h3>Encerrar incidente</h3><label>Resolução<textarea required minLength={3} maxLength={1000} value={resolution} onChange={e => setResolution(e.target.value)} placeholder="Descreva a resolução aplicada" /></label><button disabled={busy || resolution.trim().length < 3}>Registrar e encerrar</button></form> : <p><strong>Resolução:</strong> {selected.resolution}</p>}</> : <p className="empty">Selecione um incidente para ver os eventos e as tentativas.</p>}</section>
    </main>
    <section className="card demo"><div><span className="eyebrow">LABORATÓRIO</span><h2>Gerar eventos fictícios</h2><p>Envie três falhas equivalentes para abrir um incidente. Configure quantas tentativas de entrega devem falhar antes da recuperação.</p><label>Falhas simuladas na entrega<input type="number" min={0} max={20} value={simulatedFailures} onChange={e => setSimulatedFailures(Number(e.target.value))} /></label></div><div className="demo-actions"><button disabled={busy} onClick={() => void perform(async () => { const seed = crypto.randomUUID(); const time = new Date().toISOString(); const payloads = [1, 2, 3].map(i => demoEvent(i, seed, time)); for (const payload of payloads) await api.event(payload); setLastDemo(payloads[2]); await refresh() }, 'Três falhas enviadas. Selecione o incidente para acompanhar a entrega.')}>Enviar três falhas</button><button disabled={busy || !lastDemo} onClick={() => void perform(async () => { if (lastDemo) await api.event({ ...lastDemo, status: 'failure' }); await refresh() }, 'Duplicata enviada; a contagem não aumentou.')}>Reenviar duplicata</button></div></section>
    <footer>Dados e destino de entrega inteiramente fictícios · <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">Documentação da API</a></footer>
  </div>
}
