import type { Bar } from '../types'
export type PythonInstruction=string|Record<string,number|string>
export const INTEGER_LIMIT=10n**18n
function integer(value:unknown):bigint{
 if(typeof value==='number'&&Number.isSafeInteger(value))return BigInt(value)
 if(typeof value==='string'&&/^-?\d+$/.test(value))return BigInt(value)
 throw new Error('指令参数必须是可精确表示的整数；超出安全范围的常量请使用十进制字符串')
}
/** Decimal(str(float))*1_000_000, truncated toward zero, without float multiplication. */
export function priceMicros(value:number):bigint{
 if(!Number.isFinite(value)||value<=0)throw new Error('行情价格无效或超过整数边界')
 const match=String(value).match(/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i)!
 const digits=BigInt(match[1]+(match[2]||'')),power=6+Number(match[3]||0)-(match[2]?.length||0)
 const result=power>=0?digits*10n**BigInt(power):digits/10n**BigInt(-power)
 if(value>1e12||result>INTEGER_LIMIT)throw new Error('行情价格无效或超过整数边界')
 return result
}
export function evaluateProgram(program:PythonInstruction[],prices:bigint[],totals:bigint[],end:number):bigint{
 if(!program.length||program.length>256)throw new Error('指令数量必须在1至256之间')
 const stack:bigint[]=[]
 for(const instruction of program){let result:bigint
 if(typeof instruction==='object'&&instruction!==null){const entries=Object.entries(instruction);if(entries.length!==1)throw new Error('无效指令');const [operation,raw]=entries[0],value=integer(raw)
  if(operation==='const')result=value
  else if(operation==='close'&&value>=0n&&value<=500n)result=end>Number(value)?prices[end-Number(value)-1]:0n
  else if(operation==='sma'&&value>=1n&&value<=500n)result=end>=Number(value)?(totals[end]-totals[end-Number(value)])/value:0n
  else throw new Error('不支持的行情指令')
 }else if(instruction==='index')result=BigInt(end)
 else if(instruction==='not'&&stack.length)result=stack.pop()===0n?1n:0n
 else if(instruction==='select'&&stack.length>=3){const no=stack.pop()!,yes=stack.pop()!,condition=stack.pop()!;result=condition!==0n?yes:no}
 else if(stack.length>=2){const b=stack.pop()!,a=stack.pop()!;switch(instruction){case'add':result=a+b;break;case'sub':result=a-b;break;case'mul':result=a*b;break;case'div':if(a<0n||b<=0n)throw new Error('不支持的算术指令');result=a/b;break;case'mod':if(a<0n||b<=0n)throw new Error('不支持的算术指令');result=a%b;break;case'gt':result=a>b?1n:0n;break;case'lt':result=a<b?1n:0n;break;case'eq':result=a===b?1n:0n;break;default:throw new Error('不支持的算术指令')}}
 else throw new Error('指令栈不完整')
 if(result>INTEGER_LIMIT||result<-INTEGER_LIMIT||stack.length>=64)throw new Error('指令超出数值或栈限制');stack.push(result)
 }
 if(stack.length!==1||stack[0]<0n||stack[0]>9500n)throw new Error('目标仓位必须在0至9500bps之间')
 return stack[0]
}
export function generatePythonTargets(bars:Bar[],program:PythonInstruction[],maxPosition=1):{target:number[];reasons:string[]}{
 if(!bars.length||bars.length>20000)throw new Error('受限Python仅支持1至20000根K线')
 const prices=bars.map(b=>priceMicros(b.close)),totals=[0n];for(const p of prices)totals.push(totals.at(-1)!+p)
 return {target:prices.map((_,i)=>Math.min(Number(evaluateProgram(program,prices,totals,i+1))/10000,maxPosition)),reasons:bars.map(()=>'受限Python · 收盘信号')}
}
