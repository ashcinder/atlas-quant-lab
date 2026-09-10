import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import { test } from 'node:test'

const entry = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8')
const theme = readFileSync(new URL('../src/theme.css', import.meta.url), 'utf8')

test('application loads shared theme tokens before density overrides', () => {
  const themeImport = entry.indexOf("import './theme.css'")
  assert.ok(themeImport >= 0)
  assert.ok(themeImport < entry.indexOf("import './terminal-density.css'"))
})

test('both light appearance presets receive the semantic light palette', () => {
  assert.match(theme, /\[data-theme='light'\],\s*\[data-theme='white'\],\s*\[data-theme='mist'\]\s*\{/)
  for (const token of ['--bg', '--panel', '--text', '--body', '--mono', '--surface-input']) {
    assert.ok(theme.includes(`${token}:`))
  }
})
