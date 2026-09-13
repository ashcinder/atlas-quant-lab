import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AtlasShell from './AtlasShell'

vi.mock('./App', () => ({ default: () => <input aria-label="Strategy draft" defaultValue="" /> }))
vi.mock('./journal/components/investment-app', () => ({ default: () => <h1>Journal fixture</h1> }))
vi.mock('./journal/components/LoginScreen', () => ({ default: () => <h1>Login fixture</h1> }))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.location.hash = '' })

describe('integrated workspace shell', () => {
  it('preserves the strategy draft across lazy workspace switches, then clears it on expiry', async () => {
    window.location.hash = '#research'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ authenticated: true, registrationEnabled: true, email: 'fixture@example.test', userId: 'fixture' }) }))
    render(<AtlasShell />)
    const input = await screen.findByRole('textbox', { name: 'Strategy draft' })
    fireEvent.change(input, { target: { value: 'Private unsaved draft' } })
    fireEvent.click(screen.getByRole('link', { name: '资产总览' }))
    await act(async () => { window.location.hash = '#/journal/overview'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    await screen.findByRole('heading', { name: 'Journal fixture' })
    expect(screen.getByRole('link', { name: '策略中心' }).getAttribute('href')).toBe('#research')
    await act(async () => { window.location.hash = '#research'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect((await screen.findByRole('textbox', { name: 'Strategy draft' }) as HTMLInputElement).value).toBe('Private unsaved draft')
    act(() => window.dispatchEvent(new Event('atlas-session-expired')))
    await screen.findByRole('heading', { name: 'Login fixture' })
    expect(screen.queryByRole('textbox', { name: 'Strategy draft', hidden: true })).toBeNull()
  })

  it('does not mount or request the strategy workspace when landing directly on the journal', async () => {
    window.location.hash = '#/journal/overview'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ authenticated: true, registrationEnabled: true, email: 'fixture@example.test', userId: 'fixture' }) }))
    render(<AtlasShell />)
    await screen.findByRole('heading', { name: 'Journal fixture' })
    expect(screen.queryByRole('textbox', { name: 'Strategy draft', hidden: true })).toBeNull()
  })
})
