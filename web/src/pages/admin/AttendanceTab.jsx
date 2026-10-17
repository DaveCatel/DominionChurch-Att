import { useEffect, useState } from 'react'
import { api } from '../../api'
import { addDays, dayLabelYear, time, todayYMD } from '../../format'
import { mediaUrl } from '../../lib/media'

const PRESETS = [
  ['30 days', 30],
  ['90 days', 90],
  ['1 year', 365],
]

const matches = (q, ...fields) => {
  const needle = q.trim().toLowerCase()
  return !needle || fields.some((f) => (f || '').toLowerCase().includes(needle))
}

function AttendeeTable({ rows, q, onRemove }) {
  const shown = (rows || []).filter((a) => matches(q, a.full_name, a.phone, a.email))
  return (
    <div className="table-wrap inner">
      <table>
        <thead>
          <tr><th>Name</th><th>Phone</th><th>In</th><th>Out</th><th></th></tr>
        </thead>
        <tbody>
          {shown.length === 0 && (
            <tr><td colSpan="5" className="muted">{rows?.length ? 'No one matches your search.' : 'Nobody clocked in.'}</td></tr>
          )}
          {shown.map((a) => (
            <tr key={a.user_id}>
              <td>
                {a.full_name}
                {a.passkey_verified && (
                  <>
                    {' '}
                    <span className="badge badge-open" title="Confirmed with fingerprint or face">fingerprint</span>
                  </>
                )}
                {a.review_status === 'NEEDS_REVIEW' && (
                  <>
                    {' '}
                    <span className="badge badge-missed" title={(a.flags || []).join(', ')}>needs review</span>
                  </>
                )}
                {a.source === 'ADMIN' && (
                  <>
                    {' '}
                    <span className="badge">added by admin</span>
                  </>
                )}
              </td>
              <td>{a.phone}</td>
              <td>{time(a.clock_in)}</td>
              <td>{a.clock_out ? time(a.clock_out) : '—'}</td>
              <td className="right">
                <button className="btn btn-ghost danger-text" onClick={() => onRemove(a)}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Search for a member and mark them present (for people who could not clock in themselves).
function AddAttendee({ occurrenceId, present, onAdded }) {
  const [term, setTerm] = useState('')
  const [results, setResults] = useState([])
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const t = term.trim()
    if (t.length < 2) {
      setResults([])
      return
    }
    let alive = true
    const timer = setTimeout(() => {
      api(`/members?q=${encodeURIComponent(t)}&active=true&limit=8`)
        .then((res) => alive && setResults(res.items))
        .catch(() => {})
    }, 250)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [term])

  async function add(member) {
    setBusyId(member.id)
    setError('')
    try {
      const row = await api(`/services/occurrences/${occurrenceId}/attendance`, {
        method: 'POST',
        body: { user_id: member.id },
      })
      onAdded(row)
      setTerm('')
      setResults([])
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId('')
    }
  }

  const shown = results.filter((m) => !present.has(m.id))
  return (
    <div className="add-attendee">
      <label>
        Mark someone present
        <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Type a name or phone number" />
      </label>
      {error && <p className="error">{error}</p>}
      {term.trim().length >= 2 && shown.length === 0 && (
        <p className="muted small">{results.length ? 'Everyone found is already marked present.' : 'No member found.'}</p>
      )}
      {shown.length > 0 && (
        <ul className="list">
          {shown.map((m) => (
            <li key={m.id}>
              <span>
                <strong>{m.full_name}</strong>
                <span className="muted small"> · {[m.phone, m.email].filter(Boolean).join(' · ')}</span>
              </span>
              <button className="btn" disabled={busyId === m.id} onClick={() => add(m)}>Mark present</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function AttendanceTab() {
  const [services, setServices] = useState([])
  const [serviceId, setServiceId] = useState('') // '' = every service
  const [to, setTo] = useState(() => todayYMD())
  const [from, setFrom] = useState(() => addDays(todayYMD(), -30))
  const [mode, setMode] = useState('sessions') // 'sessions' | 'members'
  const [q, setQ] = useState('')

  const [sessions, setSessions] = useState(null)
  const [report, setReport] = useState(null)
  const [open, setOpen] = useState({}) // occurrence id -> expanded?
  const [details, setDetails] = useState({}) // occurrence id -> attendee rows
  const [error, setError] = useState('')
  const [printing, setPrinting] = useState('') // session whose PDF is being prepared

  useEffect(() => {
    api('/services').then(setServices).catch((e) => setError(e.message))
  }, [])

  function loadDetails(id) {
    api(`/services/occurrences/${id}/attendance`)
      .then((rows) => setDetails((d) => ({ ...d, [id]: rows })))
      .catch((e) => setError(e.message))
  }

  // the query: re-run whenever a filter changes
  useEffect(() => {
    setError('')
    if (!from || !to) return
    if (from > to) {
      setError('The start date is after the end date.')
      return
    }
    let alive = true
    const params = new URLSearchParams({ date_from: from, date_to: to })
    if (serviceId) params.set('service_id', serviceId)

    if (mode === 'sessions') {
      setSessions(null)
      setOpen({})
      setDetails({})
      api(`/services/occurrences?${params}`)
        .then((rows) => {
          if (!alive) return
          setSessions(rows)
          // show the most recent session that has attendees straight away
          const first = rows.find((r) => r.attendee_count > 0)
          if (first) {
            setOpen({ [first.id]: true })
            loadDetails(first.id)
          }
        })
        .catch((e) => alive && setError(e.message))
    } else {
      setReport(null)
      api(`/services/attendance/members?${params}`)
        .then((r) => alive && setReport(r))
        .catch((e) => alive && setError(e.message))
    }
    return () => {
      alive = false
    }
  }, [serviceId, from, to, mode])

  const bump = (id, delta) =>
    setSessions((cur) => cur && cur.map((o) => (o.id === id ? { ...o, attendee_count: o.attendee_count + delta } : o)))

  function addedAttendee(id, row) {
    setDetails((d) => ({ ...d, [id]: [...(d[id] || []), row] }))
    bump(id, 1)
  }

  async function removeAttendee(o, attendee) {
    if (!window.confirm(`Remove ${attendee.full_name} from this session?`)) return
    setError('')
    try {
      await api(`/services/occurrences/${o.id}/attendance/${attendee.user_id}`, { method: 'DELETE' })
      setDetails((d) => ({ ...d, [o.id]: (d[o.id] || []).filter((a) => a.user_id !== attendee.user_id) }))
      bump(o.id, -1)
    } catch (e) {
      setError(e.message)
    }
  }

  async function setStatus(o, status) {
    if (status === 'CANCELLED' && !window.confirm('Cancel this session? Members will no longer see it.')) return
    setError('')
    try {
      const updated = await api(`/services/occurrences/${o.id}`, { method: 'PATCH', body: { status } })
      setSessions((cur) => cur.map((x) => (x.id === o.id ? { ...x, status: updated.status } : x)))
    } catch (e) {
      setError(e.message)
    }
  }

  // The printable register for one session, as a PDF in a new tab (print or save it from there).
  async function printPdf(o) {
    setError('')
    setPrinting(o.id)
    const tab = window.open('', '_blank') // opened right away so phones do not block it
    try {
      const link = await api(`/services/occurrences/${o.id}/pdf-link`, { method: 'POST' })
      const url = mediaUrl(link.path)
      if (tab) tab.location.href = url
      else window.location.assign(url)
    } catch (e) {
      if (tab) tab.close()
      setError(e.message)
    } finally {
      setPrinting('')
    }
  }

  function toggle(o) {
    const isOpen = !!open[o.id]
    setOpen((cur) => ({ ...cur, [o.id]: !isOpen }))
    if (!isOpen && !details[o.id]) loadDetails(o.id)
  }

  function preset(days) {
    const today = todayYMD()
    setTo(today)
    setFrom(addDays(today, -days))
  }

  const members = report ? report.members.filter((m) => matches(q, m.full_name, m.phone, m.email)) : []

  return (
    <>
      <section className="card">
        <h3>Find who attended</h3>
        <p className="muted small">Pick a service, then press <strong>Print PDF</strong> on a session to get its attendance register (church, service, date and times, and everyone who attended).</p>

        <p className="muted small filter-label">Service</p>
        <div className="tabs wrap">
          <button className={serviceId === '' ? 'active' : ''} onClick={() => setServiceId('')}>All services</button>
          {services.map((s) => (
            <button key={s.id} className={serviceId === s.id ? 'active' : ''} onClick={() => setServiceId(s.id)}>
              {s.name}
            </button>
          ))}
        </div>

        <div className="row">
          <label>
            From
            <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <span className="muted small">Last:</span>
          {PRESETS.map(([label, days]) => (
            <button key={label} className="btn btn-ghost" type="button" onClick={() => preset(days)}>{label}</button>
          ))}
        </div>

        <label>
          Search a name or phone (optional)
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Marie or 6 77" />
        </label>

        <div className="tabs">
          <button className={mode === 'sessions' ? 'active' : ''} onClick={() => setMode('sessions')}>
            By session
          </button>
          <button className={mode === 'members' ? 'active' : ''} onClick={() => setMode('members')}>
            By member
          </button>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      {mode === 'sessions' && (
        <>
          {!sessions && !error && <p className="muted">Loading…</p>}
          {sessions && sessions.length === 0 && <p className="card muted">No sessions in this period.</p>}
          {sessions && sessions.length > 0 && (
            <ul className="card list sessions">
              {sessions.map((o) => (
                <li key={o.id} className="session">
                  <div className="session-row">
                  <button className="session-head" onClick={() => toggle(o)} aria-expanded={!!open[o.id]}>
                    <span>
                      <strong>{o.name}</strong>
                      <span className="muted"> · {dayLabelYear(o.service_date)} · {time(o.start_time)}</span>
                    </span>
                    {o.status === 'CANCELLED' ? (
                      <span className="badge badge-missed">Cancelled {open[o.id] ? '▴' : '▾'}</span>
                    ) : (
                      <span className={`badge ${o.attendee_count ? 'badge-completed' : ''}`}>
                        {o.attendee_count} attended {open[o.id] ? '▴' : '▾'}
                      </span>
                    )}
                  </button>
                  {o.status !== 'CANCELLED' && (
                    <button
                      className="btn session-print"
                      onClick={() => printPdf(o)}
                      disabled={printing === o.id}
                      title="Download or print this session's attendance register"
                    >
                      {printing === o.id ? 'Preparing…' : 'Print PDF'}
                    </button>
                  )}
                  </div>
                  {open[o.id] && (
                    <div className="session-body">
                      {o.status === 'CANCELLED' ? (
                        <p className="muted small">
                          This session was cancelled, so members do not see it.{' '}
                          <button className="btn btn-ghost" onClick={() => setStatus(o, 'SCHEDULED')}>Restore it</button>
                        </p>
                      ) : (
                        <>
                          <p className="muted small">
                            <a className="btn btn-ghost" href={`/checkin-display/${o.id}`} target="_blank" rel="noreferrer">
                              Open check-in screen
                            </a>
                          </p>
                          {details[o.id] ? (
                            <AttendeeTable rows={details[o.id]} q={q} onRemove={(a) => removeAttendee(o, a)} />
                          ) : (
                            <p className="muted small pad">Loading…</p>
                          )}
                          {details[o.id] && (
                            <AddAttendee
                              occurrenceId={o.id}
                              present={new Set(details[o.id].map((a) => a.user_id))}
                              onAdded={(row) => addedAttendee(o.id, row)}
                            />
                          )}
                          {o.attendee_count === 0 && (
                            <p className="muted small">
                              Not happening this week?{' '}
                              <button className="btn btn-ghost" onClick={() => setStatus(o, 'CANCELLED')}>Cancel this session</button>
                            </p>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {mode === 'members' && (
        <>
          {!report && !error && <p className="muted">Loading…</p>}
          {report && (
            <>
              <p className="muted">
                {report.members.length} {report.members.length === 1 ? 'member' : 'members'} attended
                {' '}across {report.sessions} {report.sessions === 1 ? 'session' : 'sessions'} in this period.
              </p>
              <div className="card table-wrap">
                <table>
                  <thead>
                    <tr><th>Name</th><th>Phone</th><th>Attended</th><th>Last time</th></tr>
                  </thead>
                  <tbody>
                    {members.length === 0 && (
                      <tr><td colSpan="4" className="muted">{report.members.length ? 'No one matches your search.' : 'Nobody attended in this period.'}</td></tr>
                    )}
                    {members.map((m) => (
                      <tr key={m.user_id}>
                        <td>{m.full_name}</td>
                        <td>{m.phone}</td>
                        <td>{m.times_attended} of {report.sessions}</td>
                        <td>{dayLabelYear(m.last_attended)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </>
  )
}
