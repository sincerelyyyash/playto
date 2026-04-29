import { LoginForm } from './components/LoginForm'
import { Dashboard } from './components/Dashboard'
import { AuthProvider, useAuth } from './context/AuthContext'

function DashboardShellSkeleton() {
  return (
    <div className="app-shell">
      <header className="border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <div className="space-y-2">
            <div className="skeleton h-4 w-40" />
            <div className="skeleton h-3 w-52" />
          </div>
          <div className="skeleton h-8 w-20" />
        </div>
      </header>
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-8">
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="surface p-4">
            <div className="skeleton h-3 w-20" />
            <div className="skeleton mt-3 h-5 w-36" />
          </div>
          <div className="surface p-4">
            <div className="skeleton h-3 w-20" />
            <div className="skeleton mt-3 h-5 w-36" />
          </div>
          <div className="surface p-4">
            <div className="skeleton h-3 w-20" />
            <div className="skeleton mt-3 h-5 w-36" />
          </div>
        </div>
        <div className="surface p-6 space-y-3">
          <div className="skeleton h-4 w-28" />
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="skeleton h-10 w-full" />
            <div className="skeleton h-10 w-full" />
            <div className="skeleton h-10 w-full" />
          </div>
        </div>
      </main>
    </div>
  )
}

function Gate() {
  const { token, bootstrapping } = useAuth()
  if (bootstrapping) {
    return <DashboardShellSkeleton />
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
