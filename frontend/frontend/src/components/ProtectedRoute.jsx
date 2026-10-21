import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { Spinner } from './ui.jsx'
import { EmptyState } from './ui.jsx'
import { IconLock } from './icons.jsx'
import Layout from './Layout.jsx'

export default function ProtectedRoute({ children, roles, loginPath = '/login' }) {
  const { isAuthenticated, ready, user } = useAuth()
  const location = useLocation()

  if (!ready) {
    return <div className="grid min-h-screen place-items-center bg-mesh text-teal-700"><Spinner className="h-8 w-8" /></div>
  }
  if (!isAuthenticated) return <Navigate to={loginPath} replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) {
    return (
      <Layout title="Not available">
        <EmptyState icon={IconLock} title="This area is not available for your account"
          text={`Your account role is “${user.role}”. Ask an administrator if you need access to this page.`} />
      </Layout>
    )
  }
  return children
}
