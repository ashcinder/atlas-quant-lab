import { Component, type ReactNode } from 'react'
import { CircleAlert, RotateCcw } from 'lucide-react'

export class WorkspaceErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }

  render() {
    if (!this.state.failed) return this.props.children
    return <section className="workspace-recovery" role="alert"><CircleAlert size={30} /><h1>这个工作区暂时无法显示</h1><p>其他工作区仍然可以使用。重试会重新载入当前工作区，尚未保存的编辑可能丢失；后端已保存的记录不会删除。</p><button onClick={() => this.setState({ failed: false })}><RotateCcw size={16} />重新载入工作区</button><small>如果反复出现，请保留操作步骤并检查前后端版本是否一致。</small></section>
  }
}
