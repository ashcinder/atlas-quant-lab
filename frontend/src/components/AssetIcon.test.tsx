import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { AssetIcon } from './AssetIcon'
import type { Asset } from '../types'

afterEach(cleanup)
const asset = (symbol: string): Asset => ({ symbol, name: symbol, asset_class: 'equity', exchange: '', currency: 'USD', timezone: 'UTC', tags: [] })

it('uses local brand artwork and recovers from a failed image when the symbol changes', () => {
  const view = render(<AssetIcon asset={asset('AAPL')} />)
  const image = view.container.querySelector('img')!
  expect(image.getAttribute('src')).toBe('/asset-icons/apple.svg')
  fireEvent.error(image)
  expect(view.container.textContent).toBe('AA')
  view.rerender(<AssetIcon asset={asset('NVDA')} />)
  expect(view.container.querySelector('img')?.getAttribute('src')).toBe('/asset-icons/nvidia.svg')
})

it('renders an unknown symbol instead of the old empty React-element fallback', () => {
  const view = render(<AssetIcon asset={asset('NEW')} />)
  expect(view.container.textContent).toBe('NE')
  expect(view.container.querySelector('img')).toBeNull()
})
