/** All journal requests use Atlas' authenticated, same-origin API. */
export async function journalFetch(input: RequestInfo | URL, init?: RequestInit) {
  const response = await fetch(input, { ...init, credentials: 'same-origin' })
  if (response.status === 401) window.dispatchEvent(new Event('atlas-session-expired'))
  return response
}
