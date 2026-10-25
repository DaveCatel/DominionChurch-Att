// Helpers for proving a clock-in comes from a real phone at the church.

const DEVICE_KEY = 'attendance.device'

// A random id kept in this browser. The server links each clock-in to it, so one phone
// cannot check in two different people for the same service.
export function getDeviceToken() {
  try {
    let token = localStorage.getItem(DEVICE_KEY)
    if (!token) {
      if (crypto.randomUUID) token = crypto.randomUUID()
      else token = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
      localStorage.setItem(DEVICE_KEY, token)
    }
    return token
  } catch {
    return null // storage is blocked: the server will note that the phone was not identified
  }
}

// Ask for a fresh reading and keep watching briefly so Android can improve an initial
// coarse fix. If location cannot be acquired, fail here instead of posting an empty request.
export function getLocation({ timeoutMs = 25000, targetAccuracyM = 200 } = {}) {
  return new Promise((resolve, reject) => {
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      reject(new Error('Location access requires this site to be opened over HTTPS.'))
      return
    }
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      reject(new Error('This browser cannot access location. Try opening the site in Chrome.'))
      return
    }

    let watchId = null
    let timerId = null
    let best = null
    let lastError = null
    let settled = false

    const finish = (location, message = '') => {
      if (settled) return
      settled = true
      if (timerId !== null) clearTimeout(timerId)
      if (watchId !== null) navigator.geolocation.clearWatch(watchId)
      if (message) reject(new Error(message))
      else resolve(location)
    }

    const messageFor = (error) => {
      if (error?.code === 1) {
        return 'Location permission was denied. Allow location for your browser and this site, then try again.'
      }
      if (error?.code === 2) {
        return 'Android could not get a location fix. Check device location and try near a window or outdoors.'
      }
      if (error?.code === 3) {
        return 'Location lookup timed out. Wait a little longer, then try again.'
      }
      return 'The browser could not get your location. Check its location permission, then try again.'
    }

    try {
      watchId = navigator.geolocation.watchPosition(
        (pos) => {
          const location = {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
            accuracy_m: pos.coords.accuracy,
          }
          if (!best || location.accuracy_m < best.accuracy_m) best = location
          if (location.accuracy_m <= targetAccuracyM) finish(best)
        },
        (error) => {
          lastError = error
          if (error.code === 1) finish(null, messageFor(error))
        },
        { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
      )
      timerId = setTimeout(() => {
        if (best) finish(best)
        else finish(null, messageFor(lastError))
      }, timeoutMs + 1000)
    } catch {
      finish(null, 'The browser could not start location access. Check its permission, then try again.')
    }
  })
}
