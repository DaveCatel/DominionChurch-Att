// Fingerprint / face check-in ("passkeys") in the browser. The phone keeps the private
// key and unlocks it with the member's fingerprint, face or screen lock; the server only
// ever sees the public key and signed confirmations.
import { api } from '../api'

const toBuffer = (b64u) => {
  const padded = (b64u + '='.repeat((4 - (b64u.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(padded)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}

const toBase64url = (buffer) => {
  let s = ''
  new Uint8Array(buffer).forEach((b) => (s += String.fromCharCode(b)))
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export const passkeysSupported = () =>
  typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials

// "iPhone", "Android phone"… so the member recognises it in their list
export function deviceLabel() {
  const ua = navigator.userAgent || ''
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua)) return 'iPad'
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android phone' : 'Android tablet'
  if (/Windows/.test(ua)) return 'Windows computer'
  if (/Macintosh|Mac OS/.test(ua)) return 'Mac'
  if (/Linux|CrOS/.test(ua)) return 'Computer'
  return 'My phone'
}

// Turns the browser's technical errors into something a member can act on.
function friendly(err) {
  const name = err && err.name
  if (name === 'NotAllowedError') {
    return new Error('The fingerprint or face check was cancelled or timed out. Please try again.')
  }
  if (name === 'InvalidStateError') {
    return new Error('This phone is already set up for your account.')
  }
  if (name === 'SecurityError') {
    return new Error('Fingerprint check-in needs the secure (https) address of the app, so it cannot be used here.')
  }
  if (name === 'NotSupportedError') {
    return new Error('This phone or browser does not support fingerprint or face check-in.')
  }
  return err instanceof Error ? err : new Error('The fingerprint check failed. Please try again.')
}

// Asks the phone to confirm with the member's fingerprint / face. purpose is 'clock_in'
// (with occurrence_id) or 'manage'. Returns what the server needs to verify it.
export async function assertPasskey({ purpose, occurrence_id = null }) {
  if (!passkeysSupported()) throw friendly({ name: 'NotSupportedError' })
  const options = await api('/passkeys/auth/options', { method: 'POST', body: { purpose, occurrence_id } })
  let cred
  try {
    cred = await navigator.credentials.get({
      publicKey: {
        ...options,
        challenge: toBuffer(options.challenge),
        allowCredentials: options.allowCredentials.map((c) => ({ ...c, id: toBuffer(c.id) })),
      },
    })
  } catch (err) {
    throw friendly(err)
  }
  return {
    id: cred.id,
    rawId: toBase64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toBase64url(cred.response.clientDataJSON),
      authenticatorData: toBase64url(cred.response.authenticatorData),
      signature: toBase64url(cred.response.signature),
      userHandle: cred.response.userHandle ? toBase64url(cred.response.userHandle) : null,
    },
  }
}

// Sets up this phone. A member who already has a phone set up must confirm with it first
// (pass that confirmation as `assertion`).
export async function enrollPasskey({ assertion = null } = {}) {
  if (!passkeysSupported()) throw friendly({ name: 'NotSupportedError' })
  const options = await api('/passkeys/register/options', { method: 'POST', body: assertion ? { assertion } : {} })
  let cred
  try {
    cred = await navigator.credentials.create({
      publicKey: {
        ...options,
        challenge: toBuffer(options.challenge),
        user: { ...options.user, id: toBuffer(options.user.id) },
        excludeCredentials: (options.excludeCredentials || []).map((c) => ({ ...c, id: toBuffer(c.id) })),
      },
    })
  } catch (err) {
    throw friendly(err)
  }
  return api('/passkeys/register/verify', {
    method: 'POST',
    body: {
      name: deviceLabel(),
      credential: {
        id: cred.id,
        rawId: toBase64url(cred.rawId),
        type: cred.type,
        response: {
          clientDataJSON: toBase64url(cred.response.clientDataJSON),
          attestationObject: toBase64url(cred.response.attestationObject),
          transports: cred.response.getTransports ? cred.response.getTransports() : [],
        },
      },
    },
  })
}
