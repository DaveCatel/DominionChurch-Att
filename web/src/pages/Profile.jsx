import { useEffect, useRef, useState } from 'react'
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
  const [mine, setMine] = useState(null) // my department memberships
  const [allDepartments, setAllDepartments] = useState([])
  const [deptError, setDeptError] = useState('')
  const [deptBusy, setDeptBusy] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  useEffect(() => {
    api('/attendance/me').then(setHistory).catch(() => {})
    api('/users/me/departments').then(setMine).catch((e) => setDeptError(e.message))
    api('/departments').then(setAllDepartments).catch(() => {})
  }, [])

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
    PENDING: ['Waiting for approval', ''],
    REJECTED: ['Not approved', 'badge-missed'],
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
    <>
      <h1>Your profile</h1>
      <section className="card profile-head">
        <Avatar user={user} size={88} />
        <div>
          <strong>{user.full_name}</strong>
          <p className="muted small">{user.role === 'admin' ? 'Administrator' : 'Member'}</p>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={upload} />
          <button className="btn" onClick={() => fileRef.current.click()}>Change photo</button>
        </div>
      </section>

      <form className="card" onSubmit={save}>
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
        {msg.text && <p className={msg.type === 'ok' ? 'success' : 'error'}>{msg.text}</p>}
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button>
      </form>

      {showPassword ? (
        <>
          <ChangePassword onDone={() => setShowPassword(false)} />
          <button type="button" className="btn btn-ghost" onClick={() => setShowPassword(false)}>
            Cancel
          </button>
        </>
      ) : (
        <section className="card service-head">
          <div>
            <h3>Password</h3>
            <p className="muted small">Change the password you use to sign in.</p>
          </div>
          <button type="button" className="btn" onClick={() => setShowPassword(true)}>
            Change password
          </button>
        </section>
      )}

      <PasskeySetup />

      <h2>My departments</h2>
      {deptError && <p className="error">{deptError}</p>}
      {mine && mine.length === 0 && <p className="card muted">You have not joined any department yet.</p>}
      {mine && mine.length > 0 && (
        <ul className="card list">
          {mine.map((d) => (
            <li key={d.department_id}>
              <span>
                <strong>{d.name}</strong>{' '}
                <span className={`badge ${STATUS[d.status][1]}`}>{STATUS[d.status][0]}</span>
              </span>
              <span className="actions">
                {d.status === 'REJECTED' && (
                  <button className="btn btn-ghost" disabled={deptBusy === d.department_id} onClick={() => requestDepartment(d.department_id)}>
                    Ask again
                  </button>
                )}
                <button className="btn btn-ghost" disabled={deptBusy === d.department_id} onClick={() => leaveDepartment(d)}>
                  {d.status === 'ACTIVE' ? 'Leave' : d.status === 'PENDING' ? 'Cancel request' : 'Remove'}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {joinable.length > 0 && (
        <div className="card">
          <h3>Join a department</h3>
          <ul className="list">
            {joinable.map((d) => (
              <li key={d.id}>
                <span>
                  <strong>{d.name}</strong>
                  {d.description && <span className="muted small"> · {d.description}</span>}
                </span>
                <button className="btn" disabled={deptBusy === d.id} onClick={() => requestDepartment(d.id)}>
                  Request to join
                </button>
              </li>
            ))}
          </ul>
          <p className="muted small">An admin has to approve your request before you are a member.</p>
        </div>
      )}

      <h2>My attendance</h2>
      {history.length === 0 ? (
        <p className="card muted">No attendance recorded yet.</p>
      ) : (
        <ul className="card list">
          {history.map((h) => (
            <li key={h.occurrence_id}>
              <span><strong>{h.name}</strong> <span className="muted">· {dayLabel(h.service_date)}</span></span>
              <span className="muted">{time(h.clock_in)}{h.clock_out ? ` – ${time(h.clock_out)}` : ' (not clocked out)'}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}