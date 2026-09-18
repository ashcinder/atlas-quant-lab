import { Wallet, decryptKeystoreJson, encryptKeystoreJson, formatEther } from 'ethers'
import { userStorageKey } from './storage'
import { request } from './request'
export const WALLET_EVENT = 'trine-wallet-changed'
// Demo deployments may opt in to a pre-funded test signer. Production builds
// keep this disabled unless TRINE_DEMO_MODE is explicitly enabled.
// Allow runtime override via window.__TRINE_CONFIG__ for deployed containers
declare global { interface Window { __TRINE_CONFIG__?: { demoMode?: string; testPrivateKey?: string } } }
const getDemoMode = () => (window.__TRINE_CONFIG__?.demoMode as string | undefined) || import.meta.env.VITE_TRINE_DEMO_MODE as string || 'false';
const getTestKey = () => (window.__TRINE_CONFIG__?.testPrivateKey as string | undefined) || import.meta.env.VITE_TRINE_TEST_PRIVATE_KEY as string || '';
const testWallet = (import.meta.env.DEV || getDemoMode() === 'true') && getTestKey() ? new Wallet(getTestKey()) : null
export function usingTestWallet() { return !!testWallet && !localStorage.getItem(key()) }
let wallet: Wallet | null = null
let scope = ''
let expiry: ReturnType<typeof setTimeout> | undefined
function expireLater() { clearTimeout(expiry); expiry=setTimeout(lockWallet,15*60*1000) }
const key = () => userStorageKey('trine:supervisor-keystore')
const emit = () => window.dispatchEvent(new Event(WALLET_EVENT))
export function lockWallet() { wallet = null; scope = ''; clearTimeout(expiry); emit() }
export function walletAddress() { try { return JSON.parse(localStorage.getItem(key()) || '{}').address || testWallet?.address || '' } catch { return '' } }
export function unlockedWallet() { if (scope !== key()) wallet = null; return wallet || (usingTestWallet() ? testWallet : null) }
export async function saveWallet(privateKey: string, password: string) {
  if (password.length < 12) throw new Error('解锁密码至少 12 个字符')
  const next = new Wallet(privateKey.trim())
  const encrypted = await encryptKeystoreJson({address:next.address,privateKey:next.privateKey}, password)
  localStorage.setItem(key(), JSON.stringify({address:next.address, encrypted}))
  wallet=next;scope=key();expireLater();emit()
}
export async function unlockWallet(password: string) {
  const saved=JSON.parse(localStorage.getItem(key()) || '{}')
  if (!saved.encrypted) throw new Error('请先在设置中配置私钥')
  try { const decrypted=await decryptKeystoreJson(saved.encrypted,password); wallet=new Wallet(decrypted.privateKey);scope=key();expireLater();emit() } catch { throw new Error('解锁失败，请检查密码') }
}
export function removeWallet() { localStorage.removeItem(key()); lockWallet() }
export async function payOrder(id: string) {
  const signer=unlockedWallet(); if(!signer) throw new Error('请先在设置中解锁 Supervisor 账户')
  const prepared=await request<{transaction:Record<string,string>; balance_wei:string}>(`/bkc-orders/${id}/signing`)
  if(prepared.transaction.from.toLowerCase()!==signer.address.toLowerCase()) throw new Error('订单账户与已解锁账户不匹配')
  const tx=prepared.transaction
  const cost=BigInt(tx.value)+BigInt(tx.gasLimit)*BigInt(tx.gasPrice)
  if(BigInt(prepared.balance_wei)<cost) throw new Error(`余额不足，需至少 ${formatEther(cost)} BKC（含最大手续费）`)
  const raw=await signer.signTransaction({...tx,nonce:Number(tx.nonce),chainId:BigInt(tx.chainId),type:0})
  const result=await request<{transaction_hash:string}>(`/bkc-orders/${id}/broadcast`,{method:'POST',body:JSON.stringify({raw_transaction:raw})})
  emit(); return result.transaction_hash
}
window.addEventListener('atlas-session-expired',lockWallet)
window.addEventListener('trine-session-lock',lockWallet)
