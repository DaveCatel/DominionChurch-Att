import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useAuth } from '../../auth.jsx'
import { dateShort, dayLabelYear } from '../../format'
import Avatar from '../../components/Avatar.jsx'

const PAGE = 50

const DEPT_STATUS = {
  ACTIVE: '',
  PENDING: ' (waiting for approval)',
  REJECTED: ' (not approved)',
}

// The editor that opens under a member's row.
function MemberPanel({ member, departments, isSelf, onChange }) {
  const initial = {
    full_name: member.full_name,
    email: member.email || '',
    phone: member.phone || '',
    is_admin: member.role === 'admin',
    is_active: member.is_active,
  }
  const [f, setF] = useState(initial)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [password, setPassword] = useState('')

  async function run(label, fn) {
    setBusy(label)
    setError('')
    setNote('')
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const save = (e) => {
    e.preventDefault()
    const body = {}
    if (f.full_name.trim() !== initial.full_name) body.full_name = f.full_name.trim()
    if (f.email.trim() !== initial.email) body.email = f.email.trim()
    if (f.phone.trim() !== initial.phone) body.phone = f.phone.trim()
    if (f.is_admin !== initial.is_admin) body.role = f.is_admin ? 'admin' : 'member'
    if (f.is_active !== initial.is_active) body.is_active = f.is_active
    if (Object.keys(body).length === 0) return setNote('Nothing to save.')
    run('save', async () => {
      onChange(await api(`/members/${member.id}`, { method: 'PATCH', body }))
      setNote('Saved.')
    })
  }

  const membership = (id) => member.departments.find((d) => d.department_id === id)

  const toggleDepartment = (dept) =>
    run(`dept-${dept.id}`, async () => {
      const current = membership(dept.id)
      if (current?.status === 'ACTIVE') {
        onChange(await api(`/members/${member.id}/departments/${dept.id}`, { method: 'DELETE' }))
      } else {
        onChange(
          await api(`/members/${member.id}/departments/${dept.id}`, { method: 'PUT', body: { status: 'ACTIVE' } }),
        )
      }
    })

  const resetPasskeys = () => {
    if (!window.confirm(`Remove all fingerprint / face check-in phones for ${member.full_name}? They can set a new one up from their profile.`)) return
    run('passkeys', async () => {
      onChange(await api(`/members/${member.id}/passkeys`, { method: 'DELETE' }))
      setNote('Passkeys removed.')
    })
  }

  const setTemporaryPassword = (e) => {
    e.preventDefault()
    if (password.length < 8) return setError('Use at least 8 characters.')
    run('password', async () => {
      await api(`/members/${member.id}/password`, { method: 'POST', body: { new_password: password } })
      setPassword('')
      setShowPassword(false)
      setNote('Password changed and the member was signed out. Tell them the new password and ask them to change it from their profile.')
    })
  }

  return (
    <div className="member-panel">
      <p className="muted small">
        Attended {member.times_attended} {member.times_attended === 1 ? 'time' : 'times'}
        {member.last_attended ? `, last on ${dayLabelYear(member.last_attended)}` : ''} · joined {dateShort(member.created_at)} ·
        last sign-in {member.last_login_at ? dateShort(member.last_login_at) : 'never'} ·{' '}
        fingerprint check-in {member.passkey_count ? `set up on ${member.passkey_count} ${member.passkey_count === 1 ? 'phone' : 'phones'}` : 'not set up'}
      </p>

      <form onSubmit={save}>
        <label>
          Full name
          <input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required />
        </label>
        <div className="row">
          <label>
            Email
            <input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          </label>
          <label>
            Phone
            <input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          </label>
        </div>
        <label className="check-item">
          <input
            type="checkbox"
            checked={f.is_admin}
            disabled={isSelf}
            onChange={(e) => setF({ ...f, is_admin: e.target.checked })}
          />
          <span>Administrator (can manage services, members and attendance)</span>
        </label>
        <label className="check-item">
          <input
            type="checkbox"
            checked={f.is_active}
            disabled={isSelf}
            onChange={(e) => setF({ ...f, is_active: e.target.checked })}
          />
          <span>Active (can sign in). Untick to block this person; their history is kept.</span>
        </label>
        {isSelf && <p className="muted small">You cannot remove your own admin access or deactivate yourself.</p>}
        <div className="actions">
          <button className="btn btn-primary" disabled={busy === 'save'}>
            {busy === 'save' ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>

      <fieldset className="who">
        <legend>Departments</legend>
        {departments.length === 0 && <span className="muted small">No departments yet.</span>}
        {departments.map((d) => {
          const m = membership(d.id)
          return (
            <label className="check-item" key={d.id}>
              <input
                type="checkbox"
                checked={m?.status === 'ACTIVE'}
                disabled={busy === `dept-${d.id}`}
                onChange={() => toggleDepartment(d)}
              />
              <span>
                {d.name}
                <span className="muted">{m ? DEPT_STATUS[m.status] : ''}</span>
              </span>
            </label>
          )
        })}
      </fieldset>

      <div className="actions">
        {member.passkey_count > 0 && (
          <button className="btn btn-ghost" type="button" disabled={busy === 'passkeys'} onClick={resetPasskeys}>
            Reset passkeys
          </button>
        )}
        {!showPassword ? (
          <button className="btn btn-ghost" type="button" onClick={() => setShowPassword(true)}>
            Set a temporary password
          </button>
        ) : (
          <form className="actions" onSubmit={setTemporaryPassword}>
            <input
              type="text"
              value={password}
              placeholder="New password (8+ characters)"
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="off"
            />
            <button className="btn" disabled={busy === 'password'}>Set password</button>
            <button className="btn btn-ghost" type="button" onClick={() => setShowPassword(false)}>Cancel</button>
          </form>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {note && <p className="muted small">{note}</p>}
    </div>
  )
}

export default function MembersTab() {
  const { user: me } = useAuth()
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('') // q after a short pause
  const [dept, setDept] = useState('')
  const [filter, setFilter] = useState('all') // all | admin | inactive
  const [departments, setDepartments] = useState([])
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)
  const latest = useRef(0)

  useEffect(() => {
    api('/departments/admin')
      .then((list) => setDepartments(list.filter((d) => d.is_active)))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const t = setTimeout(() => setSearch(q), 250)
    return () => clearTimeout(t)
  }, [q])

  const query = useCallback(
    (offset) => {
      const p = new URLSearchParams({ limit: PAGE, offset })
      if (search.trim()) p.set('q', search.trim())
      if (dept) p.set('department_id', dept)
      if (filter === 'admin') p.set('role', 'admin')
      if (filter === 'inactive') p.set('active', 'false')
      return `/members?${p}`
    },
    [search, dept, filter],
  )

  // first page, whenever a filter changes
  useEffect(() => {
    const id = ++latest.current
    setLoading(true)
    setError('')
    api(query(0))
      .then((res) => {
        if (id !== latest.current) return
        setItems(res.items)
        setTotal(res.total)
        setOpenId(null)
      })
      .catch((e) => id === latest.current && setError(e.message))
      .finally(() => id === latest.current && setLoading(false))
  }, [query])

  function loadMore() {
    const id = ++latest.current
    setLoading(true)
    api(query(items.length))
      .then((res) => {
        if (id !== latest.current) return
        setItems((cur) => [...cur, ...res.items])
        setTotal(res.total)
      })
      .catch((e) => id === latest.current && setError(e.message))
      .finally(() => id === latest.current && setLoading(false))
  }

  const replace = (updated) => setItems((cur) => cur.map((m) => (m.id === updated.id ? updated : m)))

  return (
    <>
      <section className="card member-filter-card" aria-label="Filter members">
        <label className="member-search-label">
          Search by name, phone or email
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Marie or 6 77" />
        </label>
        <div className="member-filter-grid">
          <label>
            Show members
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">Everyone</option>
              <option value="admin">Admins</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
          {departments.length > 0 && (
            <label>
              Department
              <select value={dept} onChange={(e) => setDept(e.target.value)}>
                <option value="">All departments</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </label>
          )}
        </div>
      </section>

      {error && <p className="error">{error}</p>}
      {!error && !loading && <p className="muted member-results-count">{total} {total === 1 ? 'member' : 'members'}</p>}
      {loading && items.length === 0 && <p className="muted">Loading…</p>}
      {!loading && items.length === 0 && !error && <p className="card muted">No members match.</p>}

      {items.length > 0 && (
        <ul className="list sessions member-list">
          {items.map((m) => (
            <li key={m.id} className="session">
              <button
                className={`session-head ${m.is_active ? '' : 'dim'}`}
                onClick={() => setOpenId(openId === m.id ? null : m.id)}
                aria-expanded={openId === m.id}
              >
                <span className="member-row-main">
                  <Avatar user={m} size={44} decorative />
                  <span className="member-row-copy">
                    <span className="member-row-name">
                      <strong>{m.full_name}</strong>
                      {m.role === 'admin' && <span className="badge">Admin</span>}
                      {!m.is_active && <span className="badge badge-missed">Inactive</span>}
                      {m.passkey_count > 0 && <span className="badge badge-open">Fingerprint</span>}
                    </span>
                    <span className="muted small member-row-contact">
                      {[m.phone, m.email].filter(Boolean).join(' · ')}
                    </span>
                  </span>
                </span>
                {m.departments.some((d) => d.status !== 'REJECTED') && (
                  <span className="member-depts">
                    {m.departments
                      .filter((d) => d.status !== 'REJECTED')
                      .map((d) => (
                        <span key={d.department_id} className={`badge member-dept-badge ${d.status === 'ACTIVE' ? 'badge-open' : ''}`}>
                          {d.name}
                          {d.status === 'PENDING' ? ' · pending' : ''}
                        </span>
                      ))}
                  </span>
                )}
              </button>
              {openId === m.id && (
                <MemberPanel member={m} departments={departments} isSelf={m.id === me?.id} onChange={replace} />
              )}
            </li>
          ))}
        </ul>
      )}

      {items.length < total && (
        <div className="actions member-load-more">
          <button className="btn" onClick={loadMore} disabled={loading}>
            {loading ? 'Loading…' : `Load more (${total - items.length} left)`}
          </button>
        </div>
      )}
    </>
  )
}
