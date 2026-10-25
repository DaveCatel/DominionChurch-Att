import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'
import { dayLabelYear, time, todayYMD } from '../../format'
import { getLocation } from '../../lib/device'

const FLAG_LABEL = {
  NO_LOCATION: 'Did not share location',
  LOW_ACCURACY: 'Weak location signal',
  FAR_FROM_VENUE: 'Far from the church',
  NEW_DEVICE: 'New phone for this account',
  NO_DEVICE_ID: 'Phone not identified',
}
export const flagLabel = (f) => FLAG_LABEL[f] || f

function ChurchLocation() {
  const [f, setF] = useState({ latitude: '', longitude: '', radius_m: 200 })
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api('/checkin/church-location')
      .then((l) => {
        setF({ latitude: l.latitude ?? '', longitude: l.longitude ?? '', radius_m: l.radius_m })
        setLoaded(true)
      })
      .catch((e) => setError(e.message))
  }, [])

  async function useMyLocation() {
    setError('')
    setMessage('')
    try {
      const location = await getLocation()
      setF((cur) => ({
        ...cur,
        latitude: location.latitude.toFixed(6),
        longitude: location.longitude.toFixed(6),
      }))
      setMessage(`Location found (accurate to about ${Math.round(location.accuracy_m)} m). Press Save to keep it.`)
    } catch (e) {
      setError(e.message)
    }
  }

  async function save(clear = false) {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const body = clear
        ? { latitude: null, longitude: null, radius_m: Number(f.radius_m) }
        : { latitude: Number(f.latitude), longitude: Number(f.longitude), radius_m: Number(f.radius_m) }
      const saved = await api('/checkin/church-location', { method: 'PUT', body })
      setF({ latitude: saved.latitude ?? '', longitude: saved.longitude ?? '', radius_m: saved.radius_m })
      setMessage(clear ? 'Church location cleared. The location check is switched off.' : 'Church location saved.')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const complete = f.latitude !== '' && f.longitude !== ''

  return (
    <section className="card">
      <h3>Church location</h3>
      <p className="muted small">
        Used by services set to "Code + location". Stand inside the church and press <strong>Use my current location</strong>,
        then Save. Phones are only accurate to about 50 to 150 m indoors, so keep the radius generous.
      </p>
      <div className="actions">
        <button className="btn" type="button" onClick={useMyLocation}>Use my current location</button>
      </div>
      <div className="row">
        <label>
          Latitude
          <input value={f.latitude} onChange={(e) => setF({ ...f, latitude: e.target.value })} inputMode="decimal" placeholder="e.g. 4.051100" />
        </label>
        <label>
          Longitude
          <input value={f.longitude} onChange={(e) => setF({ ...f, longitude: e.target.value })} inputMode="decimal" placeholder="e.g. 9.767900" />
        </label>
      </div>
      <label>
        Radius in metres
        <input type="number" min="20" max="5000" value={f.radius_m} onChange={(e) => setF({ ...f, radius_m: e.target.value })} />
      </label>
      {error && <p className="error">{error}</p>}
      {message && <p className="muted small">{message}</p>}
      {loaded && !complete && <p className="muted small">No location saved yet, so the location check is not applied.</p>}
      <div className="actions">
        <button className="btn btn-primary" disabled={busy || !complete} onClick={() => save(false)}>Save</button>
        {complete && <button className="btn btn-ghost" disabled={busy} onClick={() => save(true)}>Clear</button>}
      </div>
    </section>
  )
}

function TodaysScreens() {
  const [sessions, setSessions] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const today = todayYMD()
    api(`/services/occurrences?date_from=${today}&date_to=${today}`)
      .then((rows) => setSessions(rows.filter((o) => o.status !== 'CANCELLED').reverse()))
      .catch((e) => setError(e.message))
  }, [])

  return (
    <section className="card">
      <h3>Check-in screen</h3>
      <p className="muted small">
        Open this on a projector or tablet at church. It shows a code (and a QR code) that changes every 30 seconds.
      </p>
      {error && <p className="error">{error}</p>}
      {sessions && sessions.length === 0 && <p className="muted small">No service is scheduled for today. For another day, open its session in the Attendance tab.</p>}
      {sessions && sessions.length > 0 && (
        <ul className="list">
          {sessions.map((o) => (
            <li key={o.id}>
              <span>
                <strong>{o.name}</strong>
                <span className="muted"> · {time(o.start_time)}</span>
              </span>
              <a className="btn btn-primary" href={`/checkin-display/${o.id}`} target="_blank" rel="noreferrer">
                Open check-in screen
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ReviewQueue({ onChange }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api('/checkin/review')
      .then(setItems)
      .catch((e) => setError(e.message))
    onChange()
  }, [onChange])
  useEffect(load, [load])

  const key = (i) => `${i.occurrence_id}:${i.user_id}`

  async function approve(list) {
    setBusy(true)
    setError('')
    try {
      await api('/checkin/review/approve', {
        method: 'POST',
        body: { items: list.map((i) => ({ occurrence_id: i.occurrence_id, user_id: i.user_id })) },
      })
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(i) {
    if (!window.confirm(`Remove ${i.full_name} from ${i.service_name}? Their attendance for that session will be deleted.`)) return
    setBusy(true)
    setError('')
    try {
      await api(`/services/occurrences/${i.occurrence_id}/attendance/${i.user_id}`, { method: 'DELETE' })
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const details = (i) =>
    [
      i.distance_m != null ? `${i.distance_m} m from the church` : null,
      i.accuracy_m != null ? `accuracy ±${Math.round(i.accuracy_m)} m` : null,
      i.device_name ? i.device_name.slice(0, 60) : null,
      i.ip_address ? `IP ${i.ip_address}` : null,
    ]
      .filter(Boolean)
      .join(' · ')

  return (
    <section className="card">
      <h3>Needs review</h3>
      <p className="muted small">
        These check-ins went through but look doubtful, for example far from the church or from a new phone. Most are
        honest (weak GPS, a new phone). Press <strong>Looks fine</strong>, or <strong>Remove</strong> if you know the person was not there.
      </p>
      {error && <p className="error">{error}</p>}
      {!items && !error && <p className="muted">Loading…</p>}
      {items && items.length === 0 && <p className="muted">Nothing to review.</p>}
      {items && items.length > 0 && (
        <>
          <div className="actions">
            <button className="btn" disabled={busy} onClick={() => approve(items)}>Looks fine for all {items.length}</button>
          </div>
          <ul className="list">
            {items.map((i) => (
              <li key={key(i)} className="review-row">
                <span>
                  <strong>{i.full_name}</strong>
                  <span className="muted"> · {i.service_name} · {dayLabelYear(i.service_date)} · in at {time(i.clock_in)}</span>
                  <br />
                  <span className="flags">
                    {i.flags.map((f) => (
                      <span key={f} className="badge badge-missed">{flagLabel(f)}</span>
                    ))}
                  </span>
                  <br />
                  <span className="muted small">{details(i)}</span>
                </span>
                <span className="actions">
                  <button className="btn btn-primary" disabled={busy} onClick={() => approve([i])}>Looks fine</button>
                  <button className="btn btn-ghost danger-text" disabled={busy} onClick={() => remove(i)}>Remove</button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

export default function CheckInTab({ onChange }) {
  return (
    <>
      <TodaysScreens />
      <ReviewQueue onChange={onChange} />
      <ChurchLocation />
    </>
  )
}
