// Pictures are served by the API server. With the website on Vercel and the API on Render
// those are two different addresses, so a relative path like /api/users/avatar/abc has to be
// pointed at the API (VITE_API_URL), not at the website.
const API_ORIGIN = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export const mediaUrl = (path) => {
  if (!path) return path
  if (/^(https?:)?\/\//.test(path) || path.startsWith('data:') || path.startsWith('blob:')) return path
  return API_ORIGIN + path
}
