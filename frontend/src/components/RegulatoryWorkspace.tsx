import { useState } from 'react'
import StyleReviewWorkspace from './StyleReviewWorkspace'
import DisclosureReviewWorkspace from './DisclosureReviewWorkspace'
import './style-review.css'

export default function RegulatoryWorkspace() {
  const [section, setSection] = useState('风格监管')
  return <section>
    <div className="style-review" style={{ paddingBottom: 0 }}>
      <h1>监管辅助</h1><p>定位疑点、核对依据、保存核验过程。</p>
      <nav className="sr-tabs" aria-label="监管辅助功能">
        {['风格监管', '信息披露一致性核验'].map(name => <button key={name} aria-pressed={section === name} onClick={() => setSection(name)}>{name}</button>)}
      </nav>
    </div>
    <div hidden={section !== '风格监管'}><StyleReviewWorkspace /></div>
    <div hidden={section !== '信息披露一致性核验'}><DisclosureReviewWorkspace /></div>
  </section>
}
