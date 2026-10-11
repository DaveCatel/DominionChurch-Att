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

// A service the member can clock in to. When the service checks presence, clocking in
// asks for the code shown at church (and, for "code + location", where the phone is).
// `autoCode` comes from scanning the QR code: it checks in straight away.
export default function ServiceCard({ service: s, onChange, autoCode = '' }) {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [showCode, setShowCode] = useState(!!autoCode)
  const [code, setCode] = useState(autoCode)
  const autoRan = useRef(false)
  // NONE | ASSERT (confirm with fingerprint/face) | ENROLL (set it up first)
  const [step, setStep] = useState(s.passkey_step || 'NONE')
  useEffect(() => setStep(s.passkey_step || 'NONE'), [s.passkey_step])

  const needsCode = !!s.verification_mode && s.verification_mode !== 'NONE'
  const needsLocation = s.verification_mode === 'CODE_LOCATION'

  async function clockIn(codeValue) {
    setBusy(true)
    setError('')
    try {
      const body = { occurrence_id: s.occurrence_id, device_time: new Date().toISOString() }
      if (step === 'ASSERT') {
        setStatus('Confirm with your fingerprint or face…')
        body.passkey = await assertPasskey({ purpose: 'clock_in', occurrence_id: s.occurrence_id })
      }
      if (needsCode) {
        body.code = codeValue
        body.device_token = getDeviceToken()
        if (needsLocation) {
          setStatus('Checking your location…')
          const where = await getLocation()
          if (where) Object.assign(body, where)
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

  async function clockOut() {
    setBusy(true)
    setError('')
    try {
      const body = { occurrence_id: s.occurrence_id, device_time: new Date().toISOString() }
      onChange(await api('/attendance/clock-out', { method: 'POST', body }))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function setUpPasskey() {
    setBusy(true)
    setError('')
    try {
      await enrollPasskey()
      setStep('ASSERT')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    // a fingerprint prompt must start from a tap, so the QR link only fills the code in then
    if (autoCode && s.state === 'open' && step !== 'ASSERT' && step !== 'ENROLL' && !autoRan.current) {
      autoRan.current = true
      clockIn(autoCode)
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

      {s.state === 'open' && step === 'ENROLL' && (
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

      {s.state === 'open' && step !== 'ENROLL' && !needsCode && (
        <>
          <button className="btn btn-primary btn-big" onClick={() => clockIn()} disabled={busy}>
            {busy ? status || 'Clocking in…' : 'Clock in'}
          </button>
          {step === 'ASSERT' && <p className="muted small">You will be asked for your fingerprint or face.</p>}
        </>
      )}

      {s.state === 'open' && step !== 'ENROLL' && needsCode && !showCode && (
        <button className="btn btn-primary btn-big" onClick={() => setShowCode(true)}>
          Clock in
        </button>
      )}

      {s.state === 'open' && step !== 'ENROLL' && needsCode && showCode && (
        <form
          className="code-form"
          onSubmit={(e) => {
            e.preventDefault()
            clockIn(code)
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
            {needsLocation && ' We will also ask for your location to confirm you are at the church.'}
          </p>
          <button className="btn btn-primary btn-big" disabled={busy}>
            {busy ? status || 'Checking in…' : step === 'ASSERT' ? 'Verify with fingerprint and check in' : 'Check in'}
          </button>
        </form>
      )}

      {s.state === 'clocked_in' && (
        <>
          <div className="time-grid">
            <div className="time-box"><small>Check in</small><strong>{time(s.clock_in)}</strong></div>
            <div className="time-box pending"><small>Check out</small><strong>--:--</strong></div>
          </div>
          <button className="btn btn-big" onClick={clockOut} disabled={busy}>
            {busy ? 'Clocking out…' : 'Clock out'}
          </button>
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
