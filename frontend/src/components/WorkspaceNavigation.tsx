import { ArrowUpRight, CandlestickChart, FlaskConical, Gavel, Layers3, PanelLeftClose, PanelLeftOpen } from 'lucide-react'

export type WorkspaceMode = 'single' | 'portfolio' | 'research' | 'quantjudge'

const destinations = [
  { id: 'single', label: '行情与回测', detail: '单标的研究', icon: CandlestickChart },
  { id: 'portfolio', label: '投资组合', detail: '多资产配置', icon: Layers3 },
  { id: 'research', label: '策略实验室', detail: '开发与验证', icon: FlaskConical },
  { id: 'quantjudge', label: '策略市场', detail: 'QuantJudge', icon: Gavel },
] as const

export function WorkspaceNavigation({ mode, onMode, collapsed, onCollapse }: {
  mode: WorkspaceMode; onMode: (mode: WorkspaceMode) => void; collapsed: boolean; onCollapse: () => void
}) {
  return <aside className="workspace-navigation">
    <a className="workspace-brand" href="#single" onClick={(event) => { event.preventDefault(); onMode('single') }} aria-label="Atlas 首页">
      <span className="workspace-monogram">A<span>↗</span></span><span><strong>Atlas</strong><small>QUANT WORKSPACE</small></span>
    </a>
    <span className="navigation-caption">工作空间</span>
    <nav aria-label="工作模式">{destinations.map(({ id, label, detail, icon: Icon }) => <button key={id} aria-label={label} title={`${label} · ${detail}`} aria-current={mode === id ? 'page' : undefined} onClick={() => onMode(id)}>
      <Icon size={20} /><span><strong>{label}</strong><small>{detail}</small></span>
    </button>)}</nav>
    <div className="navigation-bottom"><div className="workspace-edition"><span />个人工作空间<small>本地研究 · Beta</small></div>
      <a href="/api/docs" target="_blank" rel="noreferrer" title="开发者 API 文档">API 文档<ArrowUpRight size={15} /></a>
      <button className="navigation-collapse" onClick={onCollapse} aria-label={collapsed ? '展开导航' : '收起导航'}>{collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}<span>收起导航</span></button>
    </div>
  </aside>
}
