import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'
import Avatar from './Avatar.jsx'
import churchLogo from '../images/DC_logo0.png'


const icon = (children) => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)
const HomeIcon = () => icon(<><path d="M3 11.5 12 4l9 7.5" /><path d="M5 10v10h14V10" /></>)
const UserIcon = () => icon(<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>)
const AdminIcon = () => icon(<><path d="M12 3 4 6v6c0 5 3.4 8 8 9 4.6-1 8-4 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" /></>)

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark">
              <img src={churchLogo} alt="" />
            </div>
            <span>Attendance</span>
          </div>
          <nav>
            <NavLink to="/" end><HomeIcon /><span>Home</span></NavLink>
            <NavLink to="/profile"><UserIcon /><span>Profile</span></NavLink>
            {user.role === 'admin' && <NavLink to="/admin"><AdminIcon /><span>Admin</span></NavLink>}
          </nav>
          <div className="topbar-user">
            <Avatar user={user} size={32} />
            <button
              className="btn btn-ghost btn-sm"
              onClick={async () => {
                await logout()
                navigate('/login')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="container">{children}</main>
    </>
  )
}
