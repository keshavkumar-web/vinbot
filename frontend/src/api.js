// Thin client for the chatbot backend. All calls go through the Vite proxy
// (/api -> http://localhost:8000) during development.

const BASE = '/api'

/** Create a new chat session and return its id. */
export async function createSession() {
  const res = await fetch(`${BASE}/session`, { method: 'POST' })
  if (!res.ok) throw new Error(`Failed to create session (${res.status})`)
  const data = await res.json()
  return data.session_id
}

/** Clear the server-side history for a session. */
export async function resetSession(sessionId) {
  const res = await fetch(`${BASE}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Failed to reset session (${res.status})`)
}

/**
 * Send a message and stream the reply.
 * EventSource only supports GET, so we POST and parse the SSE body manually.
 *
 * @param {string} sessionId
 * @param {string} message
 * @param {{onToken:(t:string)=>void, onDone:()=>void, onError:(m:string)=>void}} handlers
 */
export async function streamChat(sessionId, message, { onToken, onDone, onError }) {
  let res
  try {
    res = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message }),
    })
  } catch (err) {
    onError(`Network error: ${err.message}`)
    return
  }

  if (!res.ok || !res.body) {
    onError(`Request failed (${res.status})`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue

      let payload
      try {
        payload = JSON.parse(dataLine.slice('data:'.length).trim())
      } catch {
        continue
      }

      if (payload.type === 'token') onToken(payload.content)
      else if (payload.type === 'done') onDone()
      else if (payload.type === 'error') onError(payload.message)
    }
  }
}
