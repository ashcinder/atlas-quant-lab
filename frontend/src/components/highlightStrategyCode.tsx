import type { StrategyLanguage } from './strategy-languages'

export function highlightStrategyCode(code: string, language: StrategyLanguage) {
  return code.split(/(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"""[\s\S]*?"""|'[^'\n]*'|"[^"\n]*"|\b(?:from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)\b|\b\d+(?:\.\d+)?\b)/g).map((token, index) => {
    const kind = (token.startsWith('//') || token.startsWith('/*') || (token.startsWith('#') && ['python', 'r', 'julia'].includes(language))) ? 'comment' : /^['"]/.test(token) ? 'string' : /^(from|import|class|def|return|if|else|elif|for|in|while|try|except|raise|with|as|pass|True|False|None|and|or|not|const|let|var|function|export|public|static|double|float|int|void|bool|struct|enum|package|func|fn|pub|use|using|namespace|new|true|false|null)$/.test(token) ? 'keyword' : /^\d/.test(token) ? 'number' : ''
    return <span key={index} className={kind ? `syntax-${kind}` : undefined}>{token}</span>
  })
}
