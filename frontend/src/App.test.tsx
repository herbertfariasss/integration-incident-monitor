import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import App from './App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const reply = (value: unknown) => ({ ok: true, json: async () => value }) as Response

it('shows an empty state and sends three demo failures plus a duplicate', async () => {
  const posted: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    if (path.includes('/counts')) return reply({ open: 0, closed: 0 })
    if (path.startsWith('/api/v1/incidents')) return reply([])
    if (path === '/api/v1/events') {
      posted.push(JSON.parse(init!.body as string).event_id)
      return reply({ duplicate: posted.length === 4, action: 'event_recorded', event_id: posted.at(-1), incident: null })
    }
    throw Error('Unexpected request: ' + path)
  }))
  render(<App />)
  expect(await screen.findByText(/Nenhum incidente encontrado/)).toBeDefined()
  fireEvent.click(screen.getByRole('button', { name: 'Enviar três falhas' }))
  await waitFor(() => expect(posted).toHaveLength(3))
  fireEvent.click(screen.getByRole('button', { name: 'Reenviar duplicata' }))
  await waitFor(() => expect(posted).toHaveLength(4))
  expect(posted[3]).toBe(posted[2])
})

it('shows network failures', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => { throw Error('offline') }))
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Sem conexão com a API. Verifique se ela está em execução.')
})
