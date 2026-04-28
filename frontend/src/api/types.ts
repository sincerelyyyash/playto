export type Merchant = {
  id: string
  name: string
  email: string
  created_at: string
}

export type Balance = {
  total_paise: number
  held_paise: number
  available_paise: number
}

export type BankAccount = {
  id: string
  account_holder_name: string
  account_number_last4: string
  ifsc_code: string
  is_active: boolean
  created_at: string
}

export type LedgerEntry = {
  id: number
  entry_type: string
  amount_paise: number
  description: string
  payout_id: string | null
  created_at: string
}

export type Payout = {
  id: string
  amount_paise: number
  status: string
  bank_account_id: string
  attempt_count: number
  failure_reason: string | null
  processing_started_at: string | null
  last_attempt_at: string | null
  created_at: string
  updated_at: string
}

export type Paginated<T> = {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export type PayoutListResponse = {
  count: number
  results: Payout[]
}
