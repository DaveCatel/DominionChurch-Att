import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { dateShort } from '../format'
import { assertPasskey, enrollPasskey, passkeysSupported } from '../lib/webauthn'

// Profile card: set up fingerprint / face check-in on this phone.
export default function PasskeySetup() {
  const [list, setList] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const supported = passkeysSupported()

  const load = useCallback(() => api('/passkeys').then(setList).catch((e) => setError(e.message)), [])
  useEffect(() => {
    load()
  }, [load])

  async function setUp() {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      // a second phone has to be approved by the first one
      const assertion = list && list.length > 0 ? await assertPasskey({ purpose: 'manage' }) : null
      await enrollPasskey({ assertion })
      setMessage('Phone set up.')
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const has = list && list.length > 0

  return (
    <section className="card">
      <h3>Fingerprint or face check-in</h3>

      {!supported && <p className="muted small">Passkey setup isn’t available in this browser.</p>}

      {has && (
        <ul className="list">
          {list.map((p) => (
            <li key={p.id}>
              <span>
                <strong>{p.name || 'My phone'}</strong>
                <span className="muted small">
                  {' '}· added {dateShort(p.created_at)} · {p.last_used_at ? `last used ${dateShort(p.last_used_at)}` : 'not used yet'}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {supported && (
        <div className="actions">
          <button className="btn btn-primary" disabled={busy} onClick={setUp}>
            {busy ? 'Waiting for your phone…' : has ? 'Add another phone' : 'Set up on this phone'}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      {message && <p className="muted small">{message}</p>}
    </section>
  )
}
