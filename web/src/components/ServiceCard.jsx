import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { time } from '../format'
import { getDeviceToken, getLocation } from '../lib/device'
import { assertPasskey, enrollPasskey, passkeysSupported } from '../lib/webauthn'

export const BADGE = {
  upcoming: 'Later today',
  open: 'Open',
  clocked_in: 'Clocked in',
  completed: 'Attended',
  missed: 'Missed',
}

// A service the member can clock in to. When the service checks presence, the member must be at
// the church (their phone's location is checked) AND confirm with ONE of: the code shown on the
// screen at church, or their phone's fingerprint / face. Which of those a member is offered
// comes from the server (`checkin_methods`). `autoCode` comes from scanning the QR code on the
// church screen: it checks in straight away with that code.
export default function ServiceCard({ service: s, onChange, autoCode = '' }) {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [codeOpen, setCodeOpen] = useState(!!autoCode)
  const [code, setCode] = useState(autoCode)
  const [justSetUp, setJustSetUp] = useState(false) // fingerprint set up from this card a moment ago
  const autoRan = useRef(false)
  const [now, setNow] = useState(() => Date.now())

  const verified = !!s.verification_mode && s.verification_mode !== 'NONE'
  const methods = s.checkin_methods || []
  const needsSetup = !!s.needs_passkey_setup && !justSetUp
  const canPasskey = methods.includes('PASSKEY') || (justSetUp && !!s.needs_passkey_setup)
  const canCode = methods.includes('CODE')

  // method: 'PASSKEY' (fingerprint / face) or 'CODE'; the location is always collected first
  async function clockIn(method, codeValue) {
    setBusy(true)
    setError('')
    try {
      const body = { occurrence_id: s.occurrence_id, device_time: new Date().toISOString() }
      if (verified) {
        body.device_token = getDeviceToken()
        setStatus('Checking your location…')
        const where = await getLocation()
        if (where) Object.assign(body, where)
        if (method === 'PASSKEY') {
          setStatus('Confirm with your fingerprint or face…')
          body.passkey = await assertPasskey({ purpose: 'clock_in', occurrence_id: s.occurrence_id })
        } else {
          body.code = codeValue
        }
      }
      onChange(await api('/attendance/clock-in', { method: 'POST', body }))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setStatus('')
    }
  }

  // Clock-out is only possible once the service has ended (the server decides; this just
  // keeps the button honest) and, for checked services, only at the church.
  const outOpens = s.clock_out_opens_at ? new Date(s.clock_out_opens_at).getTime() : null
  const outCloses = s.clock_out_closes_at ? new Date(s.clock_out_closes_at).getTime() : null
  const outWaiting = outOpens !== null && now < outOpens
  const outClosed = outCloses !== null && now > outCloses

  useEffect(() => {
    if (s.state !== 'clocked_in') return
    const nextBoundary = [outOpens, outCloses]
      .filter((boundary) => boundary !== null && boundary > now)
      .sort((a, b) => a - b)[0]
    if (nextBoundary === undefined) return
    const wait = nextBoundary - Date.now()
    if (wait <= 0) {
      setNow(Date.now())
      return
    }
    const t = setTimeout(() => setNow(Date.now()), Math.min(wait + 250, 60000))
    return () => clearTimeout(t)
  }, [s.state, outOpens, outCloses, now])

  async function clockOut() {
    setBusy(true)
    setError('')
    try {
      const body = { occurrence_id: s.occurrence_id, device_time: new Date().toISOString() }
      if (verified) {
        setStatus('Checking your location…')
        const where = await getLocation()
        if (where) Object.assign(body, where)
      }
      if (s.clock_out_passkey) {
        setStatus('Confirm with your fingerprint or face…')
        body.passkey = await assertPasskey({ purpose: 'clock_out', occurrence_id: s.occurrence_id })
      }
      onChange(await api('/attendance/clock-out', { method: 'POST', body }))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setStatus('')
    }
  }

  async function setUpPasskey() {
    setBusy(true)
    setError('')
    try {
      await enrollPasskey()
      setJustSetUp(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    // the QR code carries the code, so it checks in with that (and the phone's location)
    if (autoCode && s.state === 'open' && verified && canCode && !autoRan.current) {
      autoRan.current = true
      clockIn('CODE', autoCode)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const range = s.end_time ? `${time(s.start_time)} – ${time(s.end_time)}` : time(s.start_time)

  return (
    <article className="card service">
      <div className="service-head">
        <div>
          <h3>{s.name}</h3>
          <p className="muted">{range}</p>
          {s.description && <p className="small">{s.description}</p>}
        </div>
        <span className={`badge ${s.state === 'upcoming' ? 'badge-outline' : `badge-${s.state}`}`}>{BADGE[s.state]}</span>
      </div>

      {s.state === 'open' && !verified && (
        <button className="btn btn-primary btn-big" onClick={() => clockIn('NONE')} disabled={busy}>
          {busy ? 'Clocking in…' : 'Clock in'}
        </button>
      )}

      {s.state === 'open' && verified && needsSetup && (
        <div>
          <p className="small">
            This service needs <strong>fingerprint or face check-in</strong>. Set it up on this phone first; it takes a few seconds.
          </p>
          {passkeysSupported() ? (
            <button className="btn btn-primary btn-big" onClick={setUpPasskey} disabled={busy}>
              {busy ? 'Waiting for your phone…' : 'Set up fingerprint or face'}
            </button>
          ) : (
            <p className="muted small">This browser cannot do it. Try Chrome or Safari on your phone, or ask an usher to mark you present.</p>
          )}
        </div>
      )}

      {s.state === 'open' && verified && !needsSetup && (
        <>
          {canPasskey && (
            <button className="btn btn-primary btn-big" onClick={() => clockIn('PASSKEY')} disabled={busy}>
              {busy ? status || 'Checking in…' : 'Clock in with fingerprint or face'}
            </button>
          )}
          {canPasskey && canCode && !codeOpen && (
            <button className="btn btn-ghost" type="button" onClick={() => setCodeOpen(true)} disabled={busy}>
              Use the check-in code instead
            </button>
          )}
          {!canPasskey && canCode && !codeOpen && (
            <button className="btn btn-primary btn-big" onClick={() => setCodeOpen(true)}>
              Clock in
            </button>
          )}
          {canCode && codeOpen && (
            <form
              className="code-form"
              onSubmit={(e) => {
                e.preventDefault()
                clockIn('CODE', code)
              }}
            >
              <label>
                Check-in code
                <input
                  className="code-input"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="6-digit code"
                  maxLength={7}
                  autoFocus
                  required
                />
              </label>
              <p className="muted small">
                Type the code shown on the screen at church, or scan the QR code on that screen with your phone's camera.
              </p>
              <button className="btn btn-primary btn-big" disabled={busy}>
                {busy ? status || 'Checking in…' : 'Check in'}
              </button>
            </form>
          )}
          <p className="muted small">
            You need to be at the church to check in; we will ask for your location
            {canPasskey ? ' and then your fingerprint or face' : ''}.
          </p>
        </>
      )}

      {s.state === 'clocked_in' && (
        <>
          <div className="time-grid">
            <div className="time-box"><small>Check in</small><strong>{time(s.clock_in)}</strong></div>
            <div className="time-box pending"><small>Check out</small><strong>--:--</strong></div>
          </div>
          {outClosed ? (
            <p className="muted small">Clock-out for this service has closed. Ask an admin if your time needs correcting.</p>
          ) : outWaiting ? (
            <>
              <button className="btn btn-big" disabled>Clock-out opens at {time(s.clock_out_opens_at)}</button>
              <p className="muted small">You can clock out when the service ends.</p>
            </>
          ) : (
            <>
              <button className="btn btn-big" onClick={clockOut} disabled={busy}>
                {busy ? status || 'Clocking out…' : 'Clock out'}
              </button>
              {(verified || s.clock_out_passkey) && (
                <p className="muted small">
                  {verified && 'You need to be at the church to clock out. '}
                  {s.clock_out_passkey && 'You will be asked for your fingerprint or face.'}
                </p>
              )}
            </>
          )}
        </>
      )}
      {s.state === 'completed' && (
        <>
          <div className="time-grid">
            <div className="time-box"><small>Check in</small><strong>{time(s.clock_in)}</strong></div>
            <div className="time-box"><small>Check out</small><strong>{time(s.clock_out)}</strong></div>
          </div>
          <p className="muted small" style={{ marginTop: '.75rem' }}>Thank you for attending.</p>
        </>
      )}
      {s.state === 'upcoming' && (
        <button className="btn btn-big" disabled>Clock-in opens at {time(s.opens_at)}</button>
      )}
      {s.state === 'missed' && <p className="muted small">This service has ended and you did not clock in.</p>}
      {error && <p className="error">{error}</p>}
    </article>
  )
}
