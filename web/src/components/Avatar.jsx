import { useEffect, useState } from 'react'
import { mediaUrl } from '../lib/media'

const COLORS = ['#0a0a0a', '#26262b', '#3f3f46', '#52525b', '#18181b', '#2e2e33']

export default function Avatar({ user, size = 40, decorative = false }) {
  const [broken, setBroken] = useState(false)
  useEffect(() => setBroken(false), [user.profile_photo_url])
  const style = { width: size, height: size, fontSize: size * 0.4 }
  // if the picture cannot be loaded (for example an old file lost on a server restart) show initials
  if (user.profile_photo_url && !broken) {
    return (
      <img
        className="avatar"
        style={style}
        src={mediaUrl(user.profile_photo_url)}
        alt={decorative ? '' : user.full_name}
        onError={() => setBroken(true)}
      />
    )
  }
  const initials = user.full_name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
  const color = COLORS[[...user.full_name].reduce((a, c) => a + c.charCodeAt(0), 0) % COLORS.length]
  return (
    <span
      className="avatar"
      style={{ ...style, background: color }}
      aria-label={decorative ? undefined : user.full_name}
      aria-hidden={decorative ? 'true' : undefined}
    >
      {initials}
    </span>
  )
}
