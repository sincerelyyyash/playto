import { LoginForm } from './components/LoginForm'
import { Dashboard } from './components/Dashboard'
import { AuthProvider, useAuth } from './context/AuthContext'

function Gate() {
  const { token, bootstrapping } = useAuth()
  if (bootstrapping) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 text-slate-600 dark:bg-slate-950 dark:text-slate-400">
        Loading…
      </div>
    )
  }
  if (!token) return <LoginForm />
  return <Dashboard />
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
