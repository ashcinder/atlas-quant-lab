import { useState } from 'react'
import { summaryText } from './report-summary'
import './summary-export.css'

export default function SummaryExport({ title, identifier, summary }: { title: string; identifier: string; summary: Record<string, unknown> }) {
  const [error, setError] = useState('')
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = `${identifier.replace(/[^a-zA-Z0-9_-]/g, '_')}-summary.json`
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function print() {
    const popup = window.open('', '_blank', 'width=850,height=1000')
    if (!popup) { setError('打印窗口被拦截，请允许弹出窗口后重试。'); return }
    popup.opener = null
    const doc = popup.document
    doc.title = title
    const style = doc.createElement('style')
    style.textContent = '@page{size:A4;margin:16mm}body{font:14px/1.6 sans-serif;color:#172b35;margin:24px}h1{font-size:24px}h2{font-size:16px;break-after:avoid}section{break-inside:avoid}pre{font:12px/1.5 sans-serif;white-space:pre-wrap;overflow-wrap:anywhere;border-bottom:1px solid #ccd6db;padding-bottom:12px}button{padding:8px 16px}@media print{button{display:none}body{margin:0}}'
    doc.head.append(style)
    const heading = doc.createElement('h1'); heading.textContent = title; doc.body.append(heading)
    const note = doc.createElement('p'); note.textContent = 'Atlas 报告摘要 · 未记录的信息不补齐；证据范围以各项说明为准。'; doc.body.append(note)
    for (const [key, value] of Object.entries(summary)) {
      const section = doc.createElement('section'), label = doc.createElement('h2'), content = doc.createElement('pre')
      label.textContent = key; content.textContent = summaryText(value); section.append(label, content); doc.body.append(section)
    }
    const button = doc.createElement('button'); button.textContent = '打印 / 保存为 PDF'; button.onclick = () => popup.print(); doc.body.append(button)
    popup.focus(); popup.print(); setError('')
  }
  return <section className="summary-export" aria-label={`${title}导出`}><div className="summary-actions"><button type="button" onClick={print}>打印摘要</button><button type="button" onClick={download}>下载JSON</button></div><details><summary>查看导出内容</summary><dl>{Object.entries(summary).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><pre>{summaryText(value)}</pre></dd></div>)}</dl></details>{error && <p role="alert">{error}</p>}</section>
}
