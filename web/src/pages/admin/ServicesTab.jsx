import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { DAYS, dayLabelYear } from '../../format'

const EMPTY = {
  name: '',
  description: '',
  service_type: 'SERVICE',
  is_recurring: true,
  day_of_week: 6,
  start_time: '09:00',
  end_time: '11:00',
  start_date: '',
  end_date: '',
  department_ids: [],
  verification_mode: 'CODE_LOCATION',
  passkey_mode: 'OPTIONAL',
}

const VERIFY = {
  NONE: 'Check-in: no checks',
  CODE_LOCATION: 'Check-in: at the church',
}

// how a member confirms, once the location is checked
const PASSKEY = {
  OFF: ' + code',
  OPTIONAL: ' + code or fingerprint',
  REQUIRED: ' + fingerprint only',
}

const hhmm = (t) => (t ? t.slice(0, 5) : '')

// the form values that match an existing service (used to pre-fill the edit form)
const fromService = (s) => ({
  name: s.name,
  description: s.description || '',
  service_type: s.service_type,
  is_recurring: s.is_recurring,
  day_of_week: s.day_of_week ?? 6,
  start_time: hhmm(s.default_start_time),
  end_time: hhmm(s.default_end_time),
  start_date: s.first_date || '',
  end_date: s.last_date || '',
  department_ids: s.department_ids || [],
  verification_mode: s.verification_mode && s.verification_mode !== 'NONE' ? 'CODE_LOCATION' : 'NONE',
  passkey_mode: s.passkey_mode || 'OFF',
})

// One form for both creating (no `service`) and editing (`service` given).
export function ServiceForm({ service, departments, locationSet, onSaved, onCancel }) {
  const editing = !!service
  const initial = editing ? fromService(service) : EMPTY
  const [f, setF] = useState(initial)
  const [restrict, setRestrict] = useState(initial.department_ids.length > 0) // who may attend
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const sameIds = (a, b) => a.length === b.length && a.every((id) => b.includes(id))

  function toggleDepartment(id) {
    setF((cur) => ({
      ...cur,
      department_ids: cur.department_ids.includes(id)
        ? cur.department_ids.filter((x) => x !== id)
        : [...cur.department_ids, id],
    }))
  }

  function createBody() {
    const body = {
      verification_mode: f.verification_mode,
      passkey_mode: f.passkey_mode,
      department_ids: restrict ? f.department_ids : [],
      name: f.name,
      description: f.description || null,
      service_type: f.service_type,
      is_recurring: f.is_recurring,
      start_time: f.start_time,
      end_time: f.end_time || null,
    }
    if (f.is_recurring) body.day_of_week = Number(f.day_of_week)
    else {
      body.start_date = f.start_date || null
      body.end_date = f.end_date || null
    }
    return body
  }

  // only send what changed, so an untouched schedule is never regenerated
  function editBody() {
    const body = {}
    if (f.name.trim() !== initial.name) body.name = f.name.trim()
    if (f.description !== initial.description) body.description = f.description || null
    if (f.service_type !== initial.service_type) body.service_type = f.service_type
    if (f.start_time !== initial.start_time) body.start_time = f.start_time
    if (f.end_time !== initial.end_time) body.end_time = f.end_time || null
    if (f.verification_mode !== initial.verification_mode) body.verification_mode = f.verification_mode
    if (f.passkey_mode !== initial.passkey_mode) body.passkey_mode = f.passkey_mode
    const ids = restrict ? f.department_ids : []
    if (!sameIds(ids, initial.department_ids)) body.department_ids = ids
    if (f.is_recurring) {
      if (Number(f.day_of_week) !== Number(initial.day_of_week)) body.day_of_week = Number(f.day_of_week)
    } else if (f.start_date !== initial.start_date || f.end_date !== initial.end_date) {
      body.start_date = f.start_date
      body.end_date = f.end_date || f.start_date
    }
    return body
  }

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (restrict && f.department_ids.length === 0) {
      return setError('Pick at least one department, or choose "Everyone".')
    }
    let body
    if (editing) {
      body = editBody()
      if (Object.keys(body).length === 0) return onCancel()
    } else {
      body = createBody()
    }
    setBusy(true)
    try {
      await api(editing ? `/services/${service.id}` : '/services', { method: editing ? 'PATCH' : 'POST', body })
      if (!editing) {
        setF(EMPTY)
        setRestrict(false)
      }
      onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className={editing ? 'edit-form' : 'card'} onSubmit={submit}>
      <h3>{editing ? `Edit ${service.name}` : 'Create a service or event'}</h3>
      <label>
        Name
        <input value={f.name} onChange={set('name')} placeholder="Sunday Service, Youth Conference…" required />
      </label>
      <label>
        Description (optional)
        <input value={f.description} onChange={set('description')} />
      </label>
      <div className="row">
        <label>
          Type
          <select value={f.service_type} onChange={set('service_type')}>
            <option value="SERVICE">Service</option>
            <option value="MEETING">Meeting</option>
            <option value="EVENT">Event / conference</option>
          </select>
        </label>
        {editing ? (
          <label>
            Repeats
            <input value={f.is_recurring ? 'Every week' : 'One-off event'} disabled />
          </label>
        ) : (
          <label>
            Repeats
            <select
              value={f.is_recurring ? 'weekly' : 'once'}
              onChange={(e) => setF({ ...f, is_recurring: e.target.value === 'weekly' })}
            >
              <option value="weekly">Every week</option>
              <option value="once">One-off (one or more days)</option>
            </select>
          </label>
        )}
      </div>

      {f.is_recurring ? (
        <label>
          Day of the week
          <select value={f.day_of_week} onChange={set('day_of_week')}>
            {DAYS.map((d, i) => (
              <option key={d} value={i}>{d}</option>
            ))}
          </select>
        </label>
      ) : (
        <div className="row">
          <label>
            First day
            <input type="date" value={f.start_date} onChange={set('start_date')} required />
          </label>
          <label>
            Last day (optional)
            <input type="date" value={f.end_date} min={f.start_date} onChange={set('end_date')} />
          </label>
        </div>
      )}

      <div className="row">
        <label>
          Starts
          <input type="time" value={f.start_time} onChange={set('start_time')} required />
        </label>
        <label>
          Ends
          <input type="time" value={f.end_time} onChange={set('end_time')} />
        </label>
      </div>
      <p className="muted small">
        Members can only clock out once the service has ended
        {f.end_time ? ` (${f.end_time})` : ', so set an end time to turn this on. Without one they can clock out whenever they like'}.
      </p>
      <fieldset className="who">
        <legend>Who can attend</legend>
        <label className="check-item">
          <input type="radio" name={`who-${service?.id || 'new'}`} checked={!restrict} onChange={() => setRestrict(false)} />
          <span>Everyone</span>
        </label>
        <label className="check-item">
          <input type="radio" name={`who-${service?.id || 'new'}`} checked={restrict} onChange={() => setRestrict(true)} />
          <span>Only members of selected departments</span>
        </label>
        {restrict && (
          <div className="check-list">
            {departments.length === 0 && (
              <span className="muted small">No departments yet. Create some in the Departments tab first.</span>
            )}
            {departments.map((d) => (
              <label className="check-item" key={d.id}>
                <input type="checkbox" checked={f.department_ids.includes(d.id)} onChange={() => toggleDepartment(d.id)} />
                <span>
                  {d.name}
                  {!d.is_active && <span className="muted"> (inactive)</span>}
                </span>
              </label>
            ))}
          </div>
        )}
        {restrict && <p className="muted small">Only approved members of these departments will see this service and be able to clock in.</p>}
      </fieldset>
      <fieldset className="who">
        <legend>Check-in verification</legend>
        {[
          ['CODE_LOCATION', 'On (recommended)', 'Members must be at the church to check in or clock out; their phone\'s location is checked.'],
          ['NONE', 'Off', 'Anyone signed in can clock in from anywhere.'],
        ].map(([value, title, help]) => (
          <label className="check-item" key={value}>
            <input
              type="radio"
              name={`verify-${service?.id || 'new'}`}
              checked={f.verification_mode === value}
              onChange={() => setF({ ...f, verification_mode: value })}
            />
            <span>
              {title}
              <span className="muted small"> · {help}</span>
            </span>
          </label>
        ))}
        {f.verification_mode === 'CODE_LOCATION' && !locationSet && (
          <p className="muted small">
            The church location is not set yet, so the location check is skipped. Set it in the Check-in tab.
          </p>
        )}
      </fieldset>
      {f.verification_mode === 'CODE_LOCATION' && (
        <fieldset className="who">
          <legend>How members confirm (after the location)</legend>
          {[
            ['OPTIONAL', 'Code or fingerprint (recommended)', "Each member chooses: the code from the screen at church, or their phone's fingerprint or face."],
            ['OFF', 'Code only', 'Members type the code shown on the screen at church.'],
            ['REQUIRED', 'Fingerprint or face only', 'No code. Everyone must set up fingerprint check-in on their profile first; an admin can mark anyone without it present.'],
          ].map(([value, title, help]) => (
            <label className="check-item" key={value}>
              <input
                type="radio"
                name={`passkey-${service?.id || 'new'}`}
                checked={f.passkey_mode === value}
                onChange={() => setF({ ...f, passkey_mode: value })}
              />
              <span>
                {title}
                <span className="muted small"> · {help}</span>
              </span>
            </label>
          ))}
          {f.passkey_mode === 'OPTIONAL' && (
            <p className="muted small">Fingerprint is the stronger check, because a friend cannot use it for you. Choose "Fingerprint or face only" for services where that matters most.</p>
          )}
        </fieldset>
      )}
      {editing && (
        <p className="muted small">
          Changes to the day or time apply to upcoming sessions nobody has clocked in to yet. Past
          sessions and their attendance stay as they were.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving…' : editing ? 'Save changes' : 'Create'}
        </button>
        {editing && (
          <button className="btn btn-ghost" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

export default function ServicesTab() {
  const [services, setServices] = useState(null)
  const [departments, setDepartments] = useState([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('all')
  const navigate = useNavigate()
  const location = useLocation()

  const load = useCallback(() => {
    setError('')
    api('/services').then(setServices).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    api('/departments/admin').then(setDepartments).catch(() => {})
  }, [])

  const visibleServices = useMemo(() => {
    if (!services) return []
    const term = query.trim().toLowerCase()
    return services.filter((s) => {
      const matchesQuery = !term || `${s.name} ${s.description || ''} ${s.service_type || ''}`.toLowerCase().includes(term)
      const matchesStatus = status === 'all' || (status === 'active' ? s.is_active : !s.is_active)
      return matchesQuery && matchesStatus
    })
  }, [services, query, status])

  const who = (s) => {
    if (!s.department_ids?.length) return 'Open to everyone'
    const names = s.department_ids.map((id) => departments.find((d) => d.id === id)?.name).filter(Boolean)
    return `${names.join(', ') || 'Selected departments'} only`
  }

  async function toggle(s) {
    setError('')
    try {
      await api(`/services/${s.id}`, { method: 'PATCH', body: { is_active: !s.is_active } })
      load()
    } catch (e) { setError(e.message) }
  }

  async function remove(s) {
    if (!window.confirm(`Delete "${s.name}"? This cannot be undone.`)) return
    setError('')
    try {
      await api(`/services/${s.id}`, { method: 'DELETE' })
      load()
    } catch (e) { setError(e.message) }
  }

  const when = (s) => s.is_recurring
    ? `Every ${DAYS[s.day_of_week]}`
    : s.first_date && s.last_date && s.first_date !== s.last_date
      ? `${dayLabelYear(s.first_date)} – ${dayLabelYear(s.last_date)}`
      : s.first_date ? dayLabelYear(s.first_date) : 'One-off event'

  const activeCount = services?.filter((s) => s.is_active).length || 0
  const inactiveCount = services?.filter((s) => !s.is_active).length || 0

  return (
    <div className="services-manager">
      {location.state?.notice && <div className="service-notice" role="status">{location.state.notice}</div>}
      <div className="services-toolbar">
        <div>
          <p className="eyebrow">SERVICE DIRECTORY</p>
          <h2 className="services-title">Your services</h2>
          <p className="muted">Manage schedules, attendance rules, and which services members can see.</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/admin/services/new')}>＋ Create service</button>
      </div>

      <div className="services-stats">
        <div className="services-stat"><span className="muted">Total services</span><strong>{services?.length ?? '—'}</strong></div>
        <div className="services-stat"><span className="muted">Active</span><strong>{services ? activeCount : '—'}</strong></div>
        <div className="services-stat"><span className="muted">Inactive</span><strong>{services ? inactiveCount : '—'}</strong></div>
      </div>

      <div className="services-filters">
        <label className="services-search">Search services
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name or description…" />
        </label>
        <label className="services-status-filter">Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All services</option>
            <option value="active">Active only</option>
            <option value="inactive">Inactive only</option>
          </select>
        </label>
      </div>

      {error && <p className="error service-error" role="alert">{error}</p>}
      {!services && !error && <div className="card service-loading">Loading services…</div>}
      {services && services.length === 0 && (
        <div className="service-empty card">
          <span className="service-empty-icon">＋</span>
          <h3>No services yet</h3>
          <p className="muted">Create your first service to start organizing schedules and attendance.</p>
          <button className="btn btn-primary" onClick={() => navigate('/admin/services/new')}>Create your first service</button>
        </div>
      )}
      {services && services.length > 0 && visibleServices.length === 0 && (
        <div className="service-empty card"><h3>No matching services</h3><p className="muted">Try another search or change the status filter.</p></div>
      )}
      {visibleServices.length > 0 && (
        <div className="services-list">
          {visibleServices.map((s) => (
            <article className={`service-management-card${s.is_active ? '' : ' is-inactive'}`} key={s.id}>
              <div className="service-management-main">
                <div className="service-card-title-row">
                  <h3>{s.name}</h3>
                  <span className={`service-status-pill ${s.is_active ? 'is-active' : 'is-inactive'}`}>{s.is_active ? 'Active' : 'Inactive'}</span>
                </div>
                {s.description && <p className="service-description">{s.description}</p>}
                <div className="service-meta-grid">
                  <div><span className="service-meta-label">Schedule</span><strong>{when(s)}</strong></div>
                  <div><span className="service-meta-label">Time</span><strong>{s.default_start_time?.slice(0, 5) || '—'}{s.default_end_time ? ` – ${s.default_end_time.slice(0, 5)}` : ''}</strong></div>
                  <div><span className="service-meta-label">Type</span><strong>{({ SERVICE: 'Service', MEETING: 'Meeting', EVENT: 'Event' })[s.service_type] || s.service_type}</strong></div>
                  <div><span className="service-meta-label">Attendance access</span><strong>{who(s)}</strong></div>
                </div>
                <p className="service-verification">{VERIFY[s.verification_mode === 'NONE' ? 'NONE' : 'CODE_LOCATION']}{s.verification_mode === 'NONE' ? '' : PASSKEY[s.passkey_mode] || PASSKEY.OFF}</p>
              </div>
              <div className="service-management-actions">
                <button className="btn btn-primary" onClick={() => navigate(`/admin/services/${s.id}/edit`)}>Edit service</button>
                <button className="btn btn-ghost" onClick={() => toggle(s)}>{s.is_active ? 'Deactivate' : 'Activate'}</button>
                <button className="btn btn-ghost danger-text" onClick={() => remove(s)}>Delete</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
