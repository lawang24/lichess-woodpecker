import { useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ApiError, api } from './api'
import Home from './pages/Home'
import SetDetail from './pages/SetDetail'
import type { User } from './types'

type AuthState =
  | { status: 'loading' }
  | { status: 'signed_out' }
  | { status: 'signed_in'; user: User }

function LoginCard() {
  return (
    <div className="card auth-card">
      <div className="auth-eyebrow">Authentication Required</div>
      <h2 className="auth-title">Sign in with Lichess to use Lichess Woodpecker.</h2>
      <p className="auth-copy">Your puzzle sets and cycle history are tied to your signed-in account.</p>
      <a className="btn auth-button" href="/api/auth/lichess/start">Sign In With Lichess</a>
    </div>
  )
}

export default function App() {
  const location = useLocation()
  const [authState, setAuthState] = useState<AuthState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false

    void api<{ user: User }>('/api/me')
      .then(data => {
        if (!cancelled) {
          setAuthState({ status: 'signed_in', user: data.user })
        }
      })
      .catch(error => {
        if (cancelled) {
          return
        }

        if (error instanceof ApiError && error.status === 401) {
          setAuthState({ status: 'signed_out' })
          return
        }

        console.error(error)
        setAuthState({ status: 'signed_out' })
      })

    return () => {
      cancelled = true
    }
  }, [])

  async function logout(): Promise<void> {
    try {
      await api('/api/logout', { method: 'POST' })
    } finally {
      setAuthState({ status: 'signed_out' })
    }
  }

  return (
    <>
      <div className="header">
        <div className="header-main">
          <h1>Lichess Woodpecker</h1>
          <h2>Tactical pattern training</h2>
        </div>
        {authState.status === 'signed_in' ? (
          <div className="auth-status">
            <span className="auth-identity">{authState.user.provider_username}</span>
            <button className="secondary" onClick={() => void logout()}>Log Out</button>
          </div>
        ) : null}
      </div>

      {authState.status === 'loading' ? (
        <div className="card" style={{ color: 'var(--text-dim)' }}>Loading account...</div>
      ) : authState.status === 'signed_in' ? (
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/sets/:setId" element={<SetDetail />} />
        </Routes>
      ) : location.pathname === '/' ? (
        <LoginCard />
      ) : (
        <Navigate to="/" replace />
      )}
    </>
  )
}
