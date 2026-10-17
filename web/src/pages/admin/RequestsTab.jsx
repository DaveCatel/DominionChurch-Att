import { useMemo, useState } from 'react'
import { api } from '../../api'
import { dateShort } from '../../format'

function initials(name = '') {
  return name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'M'
}

function requestDate(value) {
  if (!value) return 0
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : 0
}

export default function RequestsTab({ requests = [], onChange, loading = false, loadError = '' }) {
  const [query, setQuery] = useState('')
  const [department, setDepartment] = useState('all')
  const [sort, setSort] = useState('newest')
  const [busyKey, setBusyKey] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const departments = useMemo(() => {
    const unique = new Map()
    requests.forEach((request) => {
      if (request.department_id != null) unique.set(String(request.department_id), request.department_name || 'Unnamed department')
    })
    return [...unique.entries()].sort((a, b) => a[1].localeCompare(b[1]))
  }, [requests])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    return requests
      .filter((request) => department === 'all' || String(request.department_id) === department)
      .filter((request) => {
        if (!term) return true
        return [request.full_name, request.email, request.phone, request.department_name]
          .some((value) => String(value || '').toLowerCase().includes(term))
      })
      .sort((a, b) => sort === 'oldest'
        ? requestDate(a.joined_at) - requestDate(b.joined_at)
        : requestDate(b.joined_at) - requestDate(a.joined_at))
  }, [requests, query, department, sort])

  async function refresh() {
    if (!onChange || refreshing) return
    setRefreshing(true)
    setError('')
    try {
      await onChange()
      setNotice('Request list refreshed.')
    } catch (e) {
      setError(e.message || 'Could not refresh requests. Please try again.')
    } finally {
      setRefreshing(false)
    }
  }

  async function review(request, action) {
    const key = `${request.user_id}:${request.department_id}`
    if (busyKey) return
    if (action === 'reject') {
      const confirmed = window.confirm(`Reject ${request.full_name || 'this member'}'s request to join ${request.department_name || 'this department'}?`)
      if (!confirmed) return
    }

    setBusyKey(key)
    setError('')
    setNotice('')
    try {
      await api(`/departments/memberships/${request.user_id}/${request.department_id}/${action}`, { method: 'PATCH' })
      setNotice(action === 'approve'
        ? `${request.full_name || 'Member'} was approved to join ${request.department_name || 'the department'}.`
        : `The request from ${request.full_name || 'the member'} was rejected.`)
      await onChange?.()
    } catch (e) {
      setError(e.message || 'We could not process this request. Refresh the list and try again.')
      try { await onChange?.() } catch { /* keep the original action error visible */ }
    } finally {
      setBusyKey('')
    }
  }

  return (
    <div className="join-requests-page">
      <div className="join-requests-toolbar">
        <div>
          <div className="join-requests-kicker">MEMBERSHIP WORKFLOW</div>
          <h2>Join requests</h2>
          <p className="muted">Review requests from members who want to join a church department.</p>
        </div>
        <button type="button" className="btn" onClick={refresh} disabled={refreshing || loading}>
          {refreshing ? 'Refreshing…' : '↻ Refresh list'}
        </button>
      </div>

      <div className="join-request-stats" aria-label="Join request summary">
        <div className="join-request-stat">
          <span className="join-request-stat-label">Awaiting review</span>
          <strong>{requests.length}</strong>
          <span className="muted small">Pending requests</span>
        </div>
        <div className="join-request-stat">
          <span className="join-request-stat-label">Departments</span>
          <strong>{departments.length}</strong>
          <span className="muted small">With pending requests</span>
        </div>
        <div className="join-request-stat">
          <span className="join-request-stat-label">Currently shown</span>
          <strong>{filtered.length}</strong>
          <span className="muted small">Matching your filters</span>
        </div>
      </div>

      {(error || loadError) && <div className="join-request-alert is-error" role="alert">{error || loadError}</div>}
      {notice && !error && !loadError && <div className="join-request-alert is-success" role="status">{notice}</div>}

      <div className="join-request-filters">
        <label className="join-request-search">
          <span>Search requests</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Name, email, phone, or department"
            aria-label="Search join requests"
          />
        </label>
        <label>
          <span>Department</span>
          <select value={department} onChange={(event) => setDepartment(event.target.value)}>
            <option value="all">All departments</option>
            {departments.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>
          <span>Sort by date</span>
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
        {(query || department !== 'all' || sort !== 'newest') && (
          <button type="button" className="btn btn-sm join-request-clear" onClick={() => { setQuery(''); setDepartment('all'); setSort('newest') }}>
            Clear filters
          </button>
        )}
      </div>

      {loading && requests.length === 0 ? (
        <div className="join-request-empty"><span className="join-request-empty-icon">…</span><h3>Loading requests</h3><p className="muted">Getting the latest pending department requests.</p></div>
      ) : loadError && requests.length === 0 ? (
        <div className="join-request-empty"><span className="join-request-empty-icon">!</span><h3>Requests could not be loaded</h3><p className="muted">Check your connection and try refreshing the list.</p><button type="button" className="btn btn-primary" onClick={refresh} disabled={refreshing}>Try again</button></div>
      ) : filtered.length === 0 ? (
        <div className="join-request-empty">
          <span className="join-request-empty-icon">✓</span>
          <h3>{requests.length === 0 ? 'You’re all caught up' : 'No matching requests'}</h3>
          <p className="muted">{requests.length === 0 ? 'There are no department join requests waiting for approval.' : 'Try a different search or clear your filters.'}</p>
          {requests.length > 0 && <button type="button" className="btn" onClick={() => { setQuery(''); setDepartment('all'); setSort('newest') }}>Clear filters</button>}
        </div>
      ) : (
        <div className="join-request-list">
          <div className="join-request-list-heading"><strong>Pending applications</strong><span className="muted small">{filtered.length} {filtered.length === 1 ? 'request' : 'requests'}</span></div>
          {filtered.map((request) => {
            const key = `${request.user_id}:${request.department_id}`
            const isBusy = busyKey === key
            return (
              <article className="join-request-card" key={key}>
                <div className="join-request-person-avatar" aria-hidden="true">{initials(request.full_name)}</div>
                <div className="join-request-main">
                  <div className="join-request-person-heading">
                    <div>
                      <h3>{request.full_name || 'Unnamed member'}</h3>
                      <p className="muted small">Requested {request.joined_at ? dateShort(request.joined_at) : 'date unavailable'}</p>
                    </div>
                    <span className="join-request-status">Awaiting review</span>
                  </div>
                  <div className="join-request-department"><span aria-hidden="true">↳</span> Request to join <strong>{request.department_name || 'Unnamed department'}</strong></div>
                  <div className="join-request-contact">
                    {request.email && <a href={`mailto:${request.email}`}>{request.email}</a>}
                    {request.phone && <a href={`tel:${request.phone}`}>{request.phone}</a>}
                    {!request.email && !request.phone && <span className="muted">No contact details provided</span>}
                  </div>
                  <div className="join-request-actions">
                    <button type="button" className="btn btn-primary" disabled={Boolean(busyKey)} onClick={() => review(request, 'approve')}>
                      {isBusy ? 'Processing…' : 'Approve request'}
                    </button>
                    <button type="button" className="btn join-request-reject" disabled={Boolean(busyKey)} onClick={() => review(request, 'reject')}>
                      Reject
                    </button>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      )}
      <p className="join-request-footnote">Approving a request updates the member’s department membership. Rejection removes it from this pending queue. Review the member and department details before taking action.</p>
    </div>
  )
}
