import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { apiFetch } from '../api/client'
import { useAuth } from '../context/AuthContext'
import type {
  Balance,
  BankAccount,
  LedgerEntry,
  Paginated,
  Payout,
  PayoutListResponse,
} from '../api/types'
import { formatPaiseLine } from '../utils/money'

const POLL_MS = 2000

function isNonTerminal(status: string): boolean {
  return status === 'pending' || status === 'processing'
}

function BalanceSkeleton() {
  return (
    <section>
      <div className="skeleton mb-3 h-4 w-20" />
      <div className="grid gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="surface p-4">
            <div className="skeleton h-3 w-16" />
            <div className="skeleton mt-3 h-5 w-36" />
          </div>
        ))}
      </div>
    </section>
  )
}

function TableSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 shadow-sm">
      <div className="border-b border-slate-800 bg-slate-800/60 px-3 py-3">
        <div className="skeleton h-3 w-64" />
      </div>
      <div className="space-y-3 px-3 py-4">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton h-4 w-full" />
        ))}
      </div>
    </div>
  )
}

export function Dashboard() {
  const { merchant, logout } = useAuth()
  const [balance, setBalance] = useState<Balance | null>(null)
  const [ledger, setLedger] = useState<LedgerEntry[]>([])
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([])
  const [payouts, setPayouts] = useState<Payout[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [amountInput, setAmountInput] = useState('')
  const [bankId, setBankId] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [coreLoading, setCoreLoading] = useState(true)

  const payoutsRef = useRef(payouts)
  useLayoutEffect(() => {
    payoutsRef.current = payouts
  }, [payouts])

  const refreshCore = useCallback(async () => {
    const [b, banksRaw, payoutsRaw, ledgerRaw] = await Promise.all([
      apiFetch<Balance>('me/balance/'),
      apiFetch<Paginated<BankAccount> | BankAccount[]>('bank-accounts/'),
      apiFetch<PayoutListResponse>('payouts/?limit=25'),
      apiFetch<Paginated<LedgerEntry>>('me/ledger/?limit=25'),
    ])
    setBalance(b)
    const banks = Array.isArray(banksRaw) ? banksRaw : banksRaw.results
    setBankAccounts(banks)
    setPayouts(payoutsRaw.results)
    setLedger(ledgerRaw.results)
    setBankId((prev) => prev || (banks[0]?.id ?? ''))
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        if (!cancelled) setCoreLoading(true)
        await refreshCore()
      } catch (e) {
        if (!cancelled) {
          setLoadError(e instanceof Error ? e.message : 'Failed to load data')
        }
      } finally {
        if (!cancelled) setCoreLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [refreshCore])

  useEffect(() => {
    const id = window.setInterval(async () => {
      const watch = payoutsRef.current.filter((p) => isNonTerminal(p.status))
      if (watch.length === 0) return
      try {
        const updates = await Promise.all(
          watch.map((p) => apiFetch<Payout>(`payouts/${p.id}/`)),
        )
        setPayouts((prev) => {
          const byId = new Map(prev.map((p) => [p.id, p]))
          for (const u of updates) byId.set(u.id, u)
          return [...byId.values()].sort(
            (a, b) =>
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          )
        })
        const b = await apiFetch<Balance>('me/balance/')
        setBalance(b)
      } catch {
        /* ignore transient poll errors */
      }
    }, POLL_MS)
    return () => window.clearInterval(id)
  }, [])

  async function onCreatePayout(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    const amount_paise = Number.parseInt(amountInput, 10)
    if (!Number.isFinite(amount_paise) || amount_paise < 1) {
      setFormError('Amount must be a positive whole number of paise.')
      return
    }
    if (!bankId) {
      setFormError('Select a bank account.')
      return
    }
    setSubmitting(true)
    try {
      const idempotencyKey = crypto.randomUUID()
      await apiFetch<Payout>('payouts/', {
        method: 'POST',
        body: JSON.stringify({
          amount_paise,
          bank_account_id: bankId,
        }),
        idempotencyKey,
      })
      setAmountInput('')
      await refreshCore()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Payout failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="border-b border-slate-800 bg-slate-900">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-4">
          <div>
            <h1 className="text-lg font-semibold">Merchant dashboard</h1>
            {merchant ? (
              <p className="text-sm text-slate-400">
                {merchant.name} · {merchant.email}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => logout()}
            className="mono-button-secondary"
          >
            Log out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-8 px-4 py-8">
        {loadError ? (
          <p className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-slate-300">
            {loadError}
          </p>
        ) : null}

        {coreLoading ? <BalanceSkeleton /> : null}

        {!coreLoading && balance ? (
          <section>
            <h2 className="mb-3 text-base font-semibold text-slate-200">
              Balance
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="surface p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Available
                </p>
                <p className="mt-1 font-mono text-sm">
                  {formatPaiseLine(balance.available_paise)}
                </p>
              </div>
              <div className="surface p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Held
                </p>
                <p className="mt-1 font-mono text-sm">
                  {formatPaiseLine(balance.held_paise)}
                </p>
              </div>
              <div className="surface p-4">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Total
                </p>
                <p className="mt-1 font-mono text-sm">
                  {formatPaiseLine(balance.total_paise)}
                </p>
              </div>
            </div>
          </section>
        ) : null}

        <section className="surface p-6">
          <h2 className="mb-4 text-base font-semibold text-slate-200">
            Request payout
          </h2>
          <form className="flex flex-col gap-4 sm:flex-row sm:items-end" onSubmit={onCreatePayout}>
            <div className="flex-1">
              <label
                htmlFor="amount"
                className="block text-sm font-medium text-slate-300"
              >
                Amount (paise, integer)
              </label>
              <input
                id="amount"
                inputMode="numeric"
                className="mono-input font-mono"
                placeholder="e.g. 5000"
                value={amountInput}
                onChange={(e) => setAmountInput(e.target.value.replace(/\D/g, ''))}
              />
            </div>
            <div className="min-w-[200px] flex-1">
              <label
                htmlFor="bank"
                className="block text-sm font-medium text-slate-300"
              >
                Bank account
              </label>
              <select
                id="bank"
                className="mono-input"
                value={bankId}
                onChange={(e) => setBankId(e.target.value)}
              >
                {bankAccounts.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.account_holder_name} · ****{b.account_number_last4}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={submitting || bankAccounts.length === 0}
              className="mono-button px-5 text-sm"
            >
              {submitting ? 'Submitting…' : 'Submit payout'}
            </button>
          </form>
          {formError ? (
            <p className="mt-3 rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300">
              {formError}
            </p>
          ) : null}
        </section>

        <section>
          <h2 className="mb-3 text-base font-semibold text-slate-200">
            Payout history
          </h2>
          {coreLoading ? <TableSkeleton rows={5} /> : null}
          {!coreLoading ? (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 shadow-sm">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-800/60">
                <tr>
                  <th className="px-3 py-2 font-medium">Created</th>
                  <th className="px-3 py-2 font-medium">Amount</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Attempts</th>
                  <th className="px-3 py-2 font-medium">Failure</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {payouts.map((p) => (
                  <tr key={p.id}>
                    <td className="px-3 py-2 font-mono text-xs text-slate-400">
                      {new Date(p.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-mono">{p.amount_paise.toLocaleString('en-IN')}p</td>
                    <td className="px-3 py-2">
                      <span
                        className={
                          isNonTerminal(p.status)
                            ? 'status-pill border border-slate-600'
                            : p.status === 'completed'
                              ? 'status-pill bg-slate-700 text-slate-100'
                              : 'status-pill'
                        }
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono">{p.attempt_count}</td>
                    <td className="max-w-xs truncate px-3 py-2 text-xs text-slate-400">
                      {p.failure_reason ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {payouts.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-slate-500">No payouts yet.</p>
            ) : null}
          </div>
          ) : null}
        </section>

        <section>
          <h2 className="mb-3 text-base font-semibold text-slate-200">
            Recent ledger
          </h2>
          {coreLoading ? <TableSkeleton rows={6} /> : null}
          {!coreLoading ? (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 shadow-sm">
            <table className="min-w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-800/60">
                <tr>
                  <th className="px-3 py-2 font-medium">When</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Amount</th>
                  <th className="px-3 py-2 font-medium">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {ledger.map((row) => (
                  <tr key={row.id}>
                    <td className="px-3 py-2 font-mono text-xs text-slate-400">
                      {new Date(row.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 capitalize">{row.entry_type}</td>
                    <td className="px-3 py-2 font-mono">
                      {row.entry_type === 'debit' ? '−' : '+'}
                      {row.amount_paise.toLocaleString('en-IN')}p
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      {row.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {ledger.length === 0 ? (
              <p className="px-3 py-6 text-center text-sm text-slate-500">No ledger entries.</p>
            ) : null}
          </div>
          ) : null}
        </section>
      </main>
    </div>
  )
}
