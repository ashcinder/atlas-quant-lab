import { request } from './request'
export type WalletProvider = { isMetaMask?: boolean; providers?: WalletProvider[]; request: (value: { method: string; params?: unknown[] }) => Promise<unknown>; on?: (name: string, fn: (...args: unknown[]) => void) => void; removeListener?: (name: string, fn: (...args: unknown[]) => void) => void }
export type WalletNetwork = { chain_id: number; chain_name: string; currency: string; rpc_url: string; genesis_hash: string }
export type ChainOrder = { id: string; status: string; transaction_hash: string | null; block_number: number | null; genesis: string; signer: string; transaction: Record<string, string>; payload: Record<string, unknown> }
export function walletProvider(): WalletProvider {
  const injected = (window as Window & { ethereum?: WalletProvider }).ethereum
  const provider = injected?.providers?.find(x => x.isMetaMask) ?? injected
  if (!provider) throw new Error('请安装 MetaMask 后连接钱包')
  return provider
}
export function walletMessage(error: unknown): string {
  const value = error as { code?: number; message?: string }
  if (value?.code === 4001) return '已取消钱包请求'
  if (value?.code === -32002) return 'MetaMask 中已有待处理请求，请先处理'
  return value?.message || '钱包操作失败'
}
export async function connectBkc() {
  const network = await request<WalletNetwork>('/wallet/network')
  const provider = walletProvider(), chainId = `0x${network.chain_id.toString(16)}`
  if (Number(await provider.request({ method: 'eth_chainId' })) !== network.chain_id) {
    try { await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] }) }
    catch (error) {
      if ((error as { code?: number }).code !== 4902) throw error
      await provider.request({ method: 'wallet_addEthereumChain', params: [{ chainId, chainName: network.chain_name, nativeCurrency: { name: 'BKC', symbol: 'BKC', decimals: 18 }, rpcUrls: [network.rpc_url] }] })
      await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] })
    }
  }
  if (Number(await provider.request({ method: 'eth_chainId' })) !== network.chain_id) throw new Error('钱包网络与 Supervisor 不一致')
  const genesis = await provider.request({ method: 'eth_getBlockByNumber', params: ['0x0', false] }) as { hash?: string }
  if (genesis?.hash?.toLowerCase() !== network.genesis_hash.toLowerCase()) throw new Error(`钱包连接了同链 ID 的另一个实例，请在 MetaMask 中将 RPC 改为 ${network.rpc_url}`)
  const accounts = await provider.request({ method: 'eth_requestAccounts' }) as string[]
  if (!accounts[0]) throw new Error('钱包未返回账户')
  return { provider, network, address: accounts[0] }
}
export async function sendBkcOrder(order: ChainOrder): Promise<string> {
  const { provider, network, address } = await connectBkc()
  if (address.toLowerCase() !== order.signer || network.genesis_hash.toLowerCase() !== order.genesis) throw new Error('请切回准备订单时的钱包和 Supervisor 网络')
  if (order.transaction_hash) return order.transaction_hash
  const hash = await provider.request({ method: 'eth_sendTransaction', params: [order.transaction] })
  if (typeof hash !== 'string' || !/^0x[0-9a-f]{64}$/i.test(hash)) throw new Error('钱包未返回有效交易哈希')
  return hash
}
