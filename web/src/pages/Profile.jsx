import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ChangePassword from '../components/ChangePassword.jsx'
import PasskeySetup from '../components/PasskeySetup.jsx'
import { useAuth } from '../auth.jsx'
import Avatar from '../components/Avatar.jsx'
import { dayLabel, time } from '../format'

export default function Profile() {
  const { user, setUser } = useAuth()
  const fileRef = useRef(null)
  const [form, setForm] = useState({ full_name: user.full_name, email: user.email || '', phone: user.phone || '' })
  const [msg, setMsg] = useState({ type: '', text: '' })
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [mine, setMine] = useState(null) // my department memberships
  const [deptLoading, setDeptLoading] = useState(true)
  const [allDepartments, setAllDepartments] = useState([])
  const [allDepartmentsLoading, setAllDepartmentsLoading] = useState(true)
  const [allDepartmentsError, setAllDepartmentsError] = useState('')
  const [deptError, setDeptError] = useState('')
  const [deptBusy, setDeptBusy] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError('')
    try {
      setHistory(await api('/attendance/me'))
    } catch (error) {
      setHistoryError(error.message)
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const loadMemberships = useCallback(async () => {
    setDeptLoading(true)
    setDeptError('')
    try {
      setMine(await api('/users/me/departments'))
    } catch (error) {
      setDeptError(error.message)
    } finally {
      setDeptLoading(false)
    }
  }, [])

  const loadAllDepartments = useCallback(async () => {
    setAllDepartmentsLoading(true)
    setAllDepartmentsError('')
    try {
      setAllDepartments(await api('/departments'))
    } catch (error) {
      setAllDepartmentsError(error.message)
    } finally {
      setAllDepartmentsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadHistory()
    loadMemberships()
    loadAllDepartments()
  }, [loadHistory, loadMemberships, loadAllDepartments])

  async function requestDepartment(id) {
    setDeptBusy(id)
    setDeptError('')
    try {
      setMine(await api('/users/me/departments', { method: 'POST', body: { department_ids: [id] } }))
    } catch (err) {
      setDeptError(err.message)
    } finally {
      setDeptBusy('')
    }
  }

  async function leaveDepartment(d) {
    if (d.status === 'ACTIVE' && !window.confirm(`Leave ${d.name}?`)) return
    setDeptBusy(d.department_id)
    setDeptError('')
    try {
      await api(`/users/me/departments/${d.department_id}`, { method: 'DELETE' })
      setMine(await api('/users/me/departments'))
    } catch (err) {
      setDeptError(err.message)
    } finally {
      setDeptBusy('')
    }
  }

  const STATUS = {
    ACTIVE: ['Member', 'badge-open'],
    PENDING: ['Pending', ''],
    REJECTED: ['Declined', 'badge-missed'],
  }
  const joinable = mine ? allDepartments.filter((d) => !mine.some((m) => m.department_id === d.id)) : []

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    setMsg({ type: '', text: '' })
    try {
      setUser(await api('/users/me', { method: 'PATCH', body: form }))
      setMsg({ type: 'ok', text: 'Profile saved.' })
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  async function upload(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (file.size > 2 * 1024 * 1024) return setMsg({ type: 'error', text: 'Image is too large (max 2 MB).' })
    const body = new FormData()
    body.append('file', file)
    try {
      setUser(await api('/users/me/avatar', { method: 'POST', form: body }))
      setMsg({ type: 'ok', text: 'Photo updated.' })
    } catch (err) {
      setMsg({ type: 'error', text: err.message })
    }
  }

  return (
    <div className="profile-page">
      <header className="profile-page-heading">
        <p className="eyebrow">ACCOUNT</p>
        <h1>Your profile</h1>
      </header>

      <nav className="profile-section-nav" aria-label="Profile sections">
        <a href="#profile-details">Details</a>
        <a href="#profile-security">Security</a>
        <a href="#profile-departments">My departments</a>
        <a href="#profile-attendance">Attendance</a>
        <a href="#profile-available-departments">Available</a>
      </nav>

      <section id="profile-details" className="profile-section" aria-labelledby="profile-details-title">
        <div className="profile-section-heading">
          <div>
            <p className="eyebrow">PERSONAL</p>
            <h2 id="profile-details-title">Profile and contact</h2>
          </div>
        </div>
        <section className="card profile-overview">
          <div className="profile-identity-column">
            <div className="profile-head">
              <Avatar user={user} size={72} />
              <div className="profile-head-copy">
                <strong>{user.full_name}</strong>
                <p className="muted small">{user.role === 'admin' ? 'Administrator' : 'Member'}</p>
                <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={upload} />
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => fileRef.current.click()}>
                  Change photo
                </button>
              </div>
            </div>
          </div>

          <form id="profile-contact-form" className="profile-form" onSubmit={save}>
            <label>
              Full name
              <input value={form.full_name} onChange={set('full_name')} required minLength={2} />
            </label>
            <label>
              Email
              <input type="email" value={form.email} onChange={set('email')} required />
            </label>
            <label>
              Phone
              <input type="tel" value={form.phone} onChange={set('phone')} required />
            </label>
            {msg.text && <p role={msg.type === 'ok' ? 'status' : 'alert'} className={msg.type === 'ok' ? 'success' : 'error'}>{msg.text}</p>}
          </form>
          <div className="profile-form-actions">
            <button type="button" className="btn" onClick={() => setShowPassword(true)}>
              Change password
            </button>
            <button type="submit" form="profile-contact-form" className="btn btn-primary" disabled={busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>
          {showPassword && (
            <div className="profile-password-edit">
              <ChangePassword onDone={() => setShowPassword(false)} />
              <button type="button" className="btn btn-ghost" onClick={() => setShowPassword(false)}>
                Cancel
              </button>
            </div>
          )}
        </section>
      </section>

      <section id="profile-security" className="profile-section" aria-labelledby="profile-security-title">
        <div className="profile-section-heading">
          <div>
            <p className="eyebrow">SIGN-IN</p>
            <h2 id="profile-security-title">Security</h2>
          </div>
        </div>
        <PasskeySetup />
      </section>

      <section id="profile-departments" className="profile-section" aria-labelledby="profile-departments-title">
        <div className="profile-section-heading">
          <div>
            <p className="eyebrow">CHURCH TEAMS</p>
            <h2 id="profile-departments-title">Departments</h2>
          </div>
        </div>
        {deptError && (
          <div className="profile-notice profile-notice-error" role="alert">
            <span>{deptError}</span>
            {mine === null && <button type="button" className="btn btn-ghost btn-sm" onClick={loadMemberships}>Try again</button>}
          </div>
        )}
        {deptLoading && mine === null ? (
          <p className="card muted" role="status">Loading your departments…</p>
        ) : mine && mine.length === 0 ? (
          <p className="card muted profile-empty-state">You have not joined any department yet.</p>
        ) : mine && mine.length > 0 ? (
          <ul className="card list profile-department-list">
            {mine.map((d) => (
              <li className="profile-department-row" key={d.department_id}>
                <div className="profile-department-copy">
                  <div className="profile-department-title">
                    <strong>{d.name}</strong>
                    <span className={`badge ${STATUS[d.status]?.[1] || ''}`}>{STATUS[d.status]?.[0] || 'Status unavailable'}</span>
                  </div>
                </div>
                <div className="profile-department-actions">
                  {d.status === 'REJECTED' && (
                    <button type="button" className="btn btn-ghost" disabled={deptBusy === d.department_id} onClick={() => requestDepartment(d.department_id)}>
                      Ask again
                    </button>
                  )}
                  <button type="button" className="btn btn-ghost" disabled={deptBusy === d.department_id} onClick={() => leaveDepartment(d)}>
                    {d.status === 'ACTIVE' ? 'Leave' : d.status === 'PENDING' ? 'Cancel request' : 'Remove'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}

      </section>

      <section id="profile-attendance" className="profile-section profile-dropdown-section" aria-labelledby="profile-attendance-title">
        <div className="profile-section-heading">
          <div>
            <p className="eyebrow">YOUR RECORD</p>
            <h2 id="profile-attendance-title">Attendance history</h2>
          </div>
        </div>
        <details className="profile-accordion">
          <summary className="profile-accordion-summary">
            <span className="profile-accordion-summary-copy">
              <strong>Attendance records</strong>
              <span className="muted small">{historyLoading ? 'Loading records…' : `${history.length} ${history.length === 1 ? 'record' : 'records'}`}</span>
            </span>
            <span className="profile-accordion-count" aria-hidden="true">{historyLoading ? '…' : history.length}</span>
          </summary>
          <div className="profile-accordion-content">
            {historyLoading ? (
              <p className="muted" role="status">Loading attendance…</p>
            ) : historyError ? (
              <div className="profile-history-error">
                <p className="error" role="alert">Could not load your attendance history: {historyError}</p>
                <button type="button" className="btn" onClick={loadHistory}>Try again</button>
              </div>
            ) : history.length === 0 ? (
              <p className="muted profile-dropdown-empty">No attendance recorded yet.</p>
            ) : (
              <ul className="list profile-attendance-list">
                {history.map((h) => (
                  <li key={h.occurrence_id}>
                    <span><strong>{h.name}</strong> <span className="muted">· {dayLabel(h.service_date)}</span></span>
                    <span className="muted">{time(h.clock_in)}{h.clock_out ? ` – ${time(h.clock_out)}` : ' (not clocked out)'}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      </section>

      <section id="profile-available-departments" className="profile-section profile-dropdown-section" aria-labelledby="profile-available-title">
        <div className="profile-section-heading">
          <div>
            <p className="eyebrow">CHURCH TEAMS</p>
            <h2 id="profile-available-title">Available departments</h2>
          </div>
        </div>
        <details className="profile-accordion">
          <summary className="profile-accordion-summary">
            <span className="profile-accordion-summary-copy">
              <strong>Browse departments</strong>
              {allDepartmentsLoading || mine === null ? <span className="muted small">Loading departments…</span> : null}
            </span>
            <span className="profile-accordion-count" aria-hidden="true">{allDepartmentsLoading || mine === null ? '…' : joinable.length}</span>
          </summary>
          <div className="profile-accordion-content">
            {allDepartmentsLoading || mine === null ? (
              <p className="muted profile-dropdown-empty" role="status">Loading available departments…</p>
            ) : allDepartmentsError ? (
              <div className="profile-history-error">
                <p className="error" role="alert">Could not load available departments: {allDepartmentsError}</p>
                <button type="button" className="btn" onClick={loadAllDepartments}>Try again</button>
              </div>
            ) : joinable.length === 0 ? (
              <p className="muted profile-dropdown-empty">There are no other departments available to join.</p>
            ) : (
              <ul className="list profile-department-list">
                {joinable.map((d) => (
                  <li className="profile-department-row" key={d.id}>
                    <div className="profile-department-copy">
                      <strong>{d.name}</strong>
                      {d.description && <p className="muted small">{d.description}</p>}
                    </div>
                    <button type="button" className="btn profile-department-request" disabled={deptBusy === d.id} onClick={() => requestDepartment(d.id)}>
                      {deptBusy === d.id ? 'Sending…' : 'Request to join'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      </section>
    </div>
  )
}
