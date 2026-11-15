export function preferredEntry(scripts: string[], root: string) {
  const prefix = root ? root + '/' : ''
  return scripts.find(path => path === prefix + 'main.py')
    ?? scripts.find(path => path === prefix + 'backtest.py')
    ?? scripts.find(path => /(^|\/)strategy_[^/]+\.py$/.test(path))
    ?? scripts[0]
}
