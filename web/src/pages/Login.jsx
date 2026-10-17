import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth.jsx'
import churchLogo from '../images/DC_logo.png'

export default function Login() {
  const { login } = useAuth()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(identifier, password)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <div className="auth-logo">
          <img
            src={churchLogo}
            alt='DC'
            />
        </div>
        <div className="auth-brand">
          <h1>DOMINION CHURCH</h1>
          <p className="brf muted">BELIEVERS ROYAL FAMILY</p>
        </div>
        <br />
        <h1>Welcome back</h1>
        <p className="muted">Sign in to clock in to a service.</p>
        <label>
          Email or phone
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary btn-big" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="muted small" style={{ textAlign: 'center', marginTop: '1rem' }}>
          <Link to="/forgot-password">Forgot your password?</Link>
        </p>
        <p className="muted small" style={{ textAlign: 'center' }}>
          New here? <Link to="/signup">Create an account</Link>
        </p>
      </form>
    </div>
  )
}
