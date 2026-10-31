import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { createRoot } from 'react-dom/client'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  Bell, Boxes, CalendarClock, ChartNoAxesCombined, CircleHelp, CreditCard, FileText, Gift, LayoutDashboard, LogOut,
  Menu, Package, Plus, RefreshCw, Search, Settings, ShieldCheck, Users, Wallet, Download, MoreHorizontal, ArrowUpRight, ArrowDownRight
} from 'lucide-react'
import './style.css'

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const inr = v => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(v || 0))
const label = s => String(s).replaceAll('_', ' ')
const PAGE = 25

/* ------------------------------------------------------------------ API helper */
let token = localStorage.getItem('bl_token') || ''
let onUnauthorized = () => {}
async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(opts.headers || {}) },
    body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body,
  })
  if (r.status === 401 && token) { onUnauthorized(); throw new Error('Session expired - please sign in again') }
  if (!r.ok) {
    let msg = await r.text()
    try { const j = JSON.parse(msg); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch {}
    throw new Error(msg.slice(0, 300))
  }
  return r.status === 204 ? null : r.json()
}
async function openPdf(id) {   // PDFs need the auth header, so fetch as a blob instead of window.open(url)
  const r = await fetch(`${API}/api/invoices/${id}/pdf`, { headers: { Authorization: 'Bearer ' + token } })
  if (!r.ok) throw new Error('Could not load the invoice PDF')
  window.open(URL.createObjectURL(await r.blob()), '_blank')
}
const toCsv = (rows, name) => {
  if (!rows.length) return
  const keys = Object.keys(rows[0])
  const csv = [keys.join(','), ...rows.map(r => keys.map(k => '"' + String(r[k] ?? '').replaceAll('"', '""') + '"').join(','))].join('\n')
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = name + '.csv'; a.click()
}

/* ------------------------------------------------------------------ resource definitions (column names match 01_schema.sql) */
const ENUMS = {
  product_type: ['service', 'goods', 'addon'], billing_period: ['daily', 'weekly', 'monthly', 'yearly'], discount_type: ['fixed', 'percentage'],
  method: ['cash', 'bank_transfer', 'card', 'upi', 'cheque', 'online_gateway'], role: ['staff', 'admin'],
}
const NUMBER = ['sales_price', 'cost_price', 'extra_price', 'value', 'billing_interval', 'term_periods', 'min_quantity', 'customer_id', 'plan_id', 'template_id',
  'payment_term_id', 'usage_limit', 'per_customer_limit', 'default_tax_id', 'amount', 'product_id', 'min_purchase_amount']
const RESOURCES = {
  Customers: { path: 'customers', cols: ['name', 'email', 'company_name', 'phone', 'tax_id', 'billing_city', 'billing_state', 'is_active'],
    fields: ['name', 'email', 'company_name', 'phone', 'tax_id', 'billing_line1', 'billing_city', 'billing_state', 'billing_postal'], required: ['name', 'email'] },
  Products: { path: 'products', admin: true, cols: ['sku', 'name', 'product_type', 'sales_price', 'cost_price', 'is_active'],
    fields: ['sku', 'name', 'description', 'product_type', 'sales_price', 'cost_price', 'default_tax_id'], required: ['sku', 'name', 'sales_price'] },
  Variants: { path: 'product_variants', admin: true, cols: ['product_id', 'attribute', 'value', 'extra_price', 'is_active'],
    fields: ['product_id', 'attribute', 'value', 'extra_price', 'sku_suffix'], required: ['product_id', 'attribute', 'value'] },
  Plans: { path: 'plans', admin: true, cols: ['name', 'billing_period', 'billing_interval', 'term_periods', 'min_quantity', 'available_from', 'available_to', 'auto_renew', 'pause_allowed', 'early_termination_allowed'],
    fields: ['name', 'description', 'billing_period', 'billing_interval', 'term_periods', 'min_quantity', 'available_from', 'available_to'], required: ['name', 'billing_period'],
    flags: ['auto_renew', 'pause_allowed', 'early_termination_allowed'] },
  Quotations: { path: 'quotations', cols: ['quotation_number', 'customer_id', 'status', 'issue_date', 'valid_until', 'total'],
    fields: ['customer_id', 'template_id'], required: ['customer_id', 'template_id'], create: '/api/quotations/from-template', newLabel: 'Quote from template' },
  Subscriptions: { path: 'subscriptions', cols: ['subscription_number', 'customer_id', 'plan_id', 'status', 'start_date', 'expiry_date', 'next_billing_date'],
    fields: ['customer_id', 'plan_id', 'payment_term_id', 'start_date', 'expiry_date'], required: ['customer_id', 'plan_id', 'payment_term_id', 'start_date'] },
  Discounts: { path: 'discounts', admin: true, cols: ['code', 'name', 'discount_type', 'value', 'min_purchase_amount', 'min_quantity', 'valid_from', 'valid_until', 'usage_limit', 'is_active'],
    fields: ['code', 'name', 'discount_type', 'value', 'min_purchase_amount', 'min_quantity', 'valid_from', 'valid_until', 'usage_limit', 'per_customer_limit'], required: ['code', 'name', 'discount_type', 'value'] },
  Invoices: { path: 'invoices', cols: ['invoice_number', 'customer_id', 'issue_date', 'due_date', 'status', 'total', 'amount_paid', 'amount_due'], noCreate: true },
  Payments: { path: 'payments', cols: ['payment_number', 'customer_id', 'transaction_date', 'method', 'status', 'amount', 'notes'], custom: 'payment' },
  Staff: { path: 'users', admin: true, cols: ['full_name', 'email', 'phone', 'role', 'is_active', 'created_at'],
    fields: ['full_name', 'email', 'phone', 'role', 'password'], required: ['full_name', 'email', 'role', 'password'] },
}
const NAV = [
  ['Overview', [['Dashboard', LayoutDashboard], ['Reports', ChartNoAxesCombined]]],
  ['Workspace', [['Customers', Users], ['Products', Package], ['Variants', Boxes], ['Plans', CalendarClock], ['Quotations', FileText], ['Subscriptions', RefreshCw], ['Discounts', Gift]]],
  ['Finance', [['Invoices', FileText], ['Payments', CreditCard]]],
  ['Administration', [['Staff', ShieldCheck]]],
]
// which row actions exist for which status
const SUB_ACTIONS = { draft: ['send_quotation', 'close'], quotation: ['confirm', 'close'], confirmed: ['activate', 'close'], active: ['pause', 'renew', 'close'], paused: ['resume', 'renew', 'close'] }
const QUOTE_ACTIONS = { draft: [['sent', 'Send']], sent: [['approved', 'Approve'], ['rejected', 'Reject']] }

/* ------------------------------------------------------------------ small UI pieces */
const Field = ({ f, form, setForm, required }) => {
  const opts = ENUMS[f]
  const type = f.includes('date') || f.endsWith('_from') || f.endsWith('_to') || f === 'valid_until' ? 'date' : f === 'password' ? 'password' : f === 'email' ? 'email' : NUMBER.includes(f) ? 'number' : 'text'
  return <label className={['description', 'billing_line1'].includes(f) ? 'wide' : ''}>{label(f)}{required ? ' *' : ''}
    {opts ? <select required={required} value={form[f] || ''} onChange={e => setForm({ ...form, [f]: e.target.value })}><option value="">Select…</option>{opts.map(v => <option key={v}>{v}</option>)}</select>
      : <input type={type} step="any" required={required} value={form[f] ?? ''} onChange={e => setForm({ ...form, [f]: e.target.value })} />}
  </label>
}
const Modal = ({ title, onClose, onSubmit, children, submit = 'Save' }) => <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
  <form className="modal" onSubmit={onSubmit}><div className="modal-head"><h2>{title}</h2><button type="button" className="icon-btn" onClick={onClose}>×</button></div>
    {children}<div className="modal-actions"><button type="button" className="btn secondary" onClick={onClose}>Cancel</button><button className="btn primary">{submit}</button></div></form></div>
const Status = ({ v }) => <span className={'status ' + String(v).toLowerCase()}>{String(v)}</span>
const Cell = ({ c, v }) => typeof v === 'boolean' ? <span className={'status ' + (v ? 'active' : 'inactive')}>{v ? 'Yes' : 'No'}</span>
  : c === 'status' ? <Status v={v} /> : ['total', 'amount', 'amount_paid', 'amount_due', 'sales_price', 'cost_price', 'extra_price'].includes(c) ? inr(v)
  : v === null || v === undefined || v === '' ? '—' : String(v).replace(/T.*$/, '')
const Pager = ({ total, offset, setOffset }) => <div className="pager"><span>{total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
  <button className="btn secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
  <button className="btn secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button></div>
const useDebounced = (v, ms = 300) => { const [d, setD] = useState(v); useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms]); return d }

/* ------------------------------------------------------------------ auth screens */
function AuthScreen({ onAuthed }) {
  const resetToken = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('reset')
  const [mode, setMode] = useState(resetToken ? 'reset' : 'login')
  const [f, setF] = useState({}); const [msg, setMsg] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const set = k => e => setF({ ...f, [k]: e.target.value })
  const submit = async e => {
    e.preventDefault(); setErr(''); setMsg(''); setBusy(true)
    try {
      if (mode === 'login' || mode === 'signup') {
        const r = await api('/api/auth/' + mode, { method: 'POST', body: mode === 'login' ? { email: f.email, password: f.password } : { email: f.email, password: f.password, full_name: f.full_name, company_name: f.company_name } })
        token = r.token; localStorage.setItem('bl_token', token); onAuthed(r.user)
      } else if (mode === 'forgot') {
        const r = await api('/api/auth/forgot-password', { method: 'POST', body: { email: f.email } })
        setMsg(r.message + (r.dev_reset_token ? ' (dev mode) Reset token: ' + r.dev_reset_token : ''))
      } else {
        const r = await api('/api/auth/reset-password', { method: 'POST', body: { token: resetToken || f.token, new_password: f.password } })
        setMsg(r.message); window.location.hash = ''; setMode('login')
      }
    } catch (x) { setErr(x.message.includes('Failed to fetch') ? 'Cannot reach the API. Is it running?' : x.message) } finally { setBusy(false) }
  }
  const titles = { login: 'Sign in', signup: 'Create your account', forgot: 'Reset your password', reset: 'Choose a new password' }
  return <div className="auth-wrap"><form className="auth-card" onSubmit={submit}>
    <div className="brand"><div className="brand-mark">b</div><div><b>brightloop</b><small>SUBSCRIPTION OS</small></div></div>
    <h2>{titles[mode]}</h2>
    {mode === 'signup' && <><label>Full name<input required value={f.full_name || ''} onChange={set('full_name')} /></label><label>Company (optional)<input value={f.company_name || ''} onChange={set('company_name')} /></label></>}
    {mode !== 'reset' && <label>Email<input type="email" required value={f.email || ''} onChange={set('email')} /></label>}
    {(mode === 'reset' && !resetToken) && <label>Reset token<input required value={f.token || ''} onChange={set('token')} /></label>}
    {mode !== 'forgot' && <label>{mode === 'reset' ? 'New password' : 'Password'}<input type="password" required value={f.password || ''} onChange={set('password')} /></label>}
    {(mode === 'signup' || mode === 'reset') && <small className="hint">More than 8 characters with an uppercase letter, a lowercase letter and a special character.</small>}
    {err && <div className="alert"><span>{err}</span></div>}{msg && <div className="notice">{msg}</div>}
    <button className="btn primary wide-btn" disabled={busy}>{busy ? 'Please wait…' : titles[mode]}</button>
    <div className="auth-links">
      {mode !== 'login' && <button type="button" onClick={() => setMode('login')}>Back to sign in</button>}
      {mode === 'login' && <><button type="button" onClick={() => setMode('signup')}>Create account</button><button type="button" onClick={() => setMode('forgot')}>Forgot password?</button></>}
    </div></form></div>
}

/* ------------------------------------------------------------------ customer portal */
function Portal({ user, logout }) {
  const [tab, setTab] = useState('subscriptions'); const [rows, setRows] = useState([]); const [err, setErr] = useState('')
  useEffect(() => { setErr(''); api('/api/portal/' + tab).then(d => setRows(d.items)).catch(e => setErr(e.message)) }, [tab])
  const cols = tab === 'subscriptions' ? ['subscription_number', 'plan_name', 'status', 'start_date', 'next_billing_date', 'amount_per_period'] : ['invoice_number', 'issue_date', 'due_date', 'status', 'total', 'amount_due']
  return <div className="portal"><header className="topbar"><div className="brand dark"><div className="brand-mark">b</div><b>brightloop</b></div>
    <div className="top-right"><span>{user.full_name}</span><button className="btn secondary" onClick={logout}><LogOut size={15} /> Sign out</button></div></header>
    <div className="content"><div className="page-heading"><div><div className="eyebrow">CUSTOMER PORTAL</div><h1>Hello, {user.full_name.split(' ')[0]}</h1><p>Your subscriptions and invoices.</p></div></div>
      <div className="tabs">{['subscriptions', 'invoices'].map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
      {err && <div className="alert"><span>{err}</span></div>}
      <div className="panel table-panel"><div className="table-scroll"><table><thead><tr>{cols.map(c => <th key={c}>{label(c)}</th>)}<th /></tr></thead>
        <tbody>{rows.map(r => <tr key={r.id}>{cols.map(c => <td key={c}><Cell c={c.startsWith('amount_per') ? 'amount' : c} v={r[c]} /></td>)}
          <td>{tab === 'invoices' && <button className="btn secondary" onClick={() => openPdf(r.id).catch(e => setErr(e.message))}><FileText size={14} /> PDF</button>}</td></tr>)}</tbody></table>
        {!rows.length && <div className="empty"><b>Nothing here yet</b></div>}</div></div></div></div>
}

/* ------------------------------------------------------------------ dashboard + reports */
function Dashboard({ go }) {
  const [s, setS] = useState(null); const [err, setErr] = useState(''); const [from, setFrom] = useState(''); const [to, setTo] = useState('')
  useEffect(() => { api(`/api/dashboard/summary?${from ? 'date_from=' + from + '&' : ''}${to ? 'date_to=' + to : ''}`).then(setS).catch(e => setErr(e.message)) }, [from, to])
  const cards = s ? [['Monthly recurring revenue', inr(s.mrr), ArrowUpRight, 'from active subscriptions'], ['Active subscriptions', s.active_subscriptions, RefreshCw, 'currently billing'],
    ['Revenue collected', inr(s.collected_total), Wallet, from || to ? 'in selected range' : 'all time'], ['Still owed', inr(s.outstanding_total), ArrowDownRight, 'confirmed + overdue invoices']] : []
  return <>{err && <div className="alert"><span>{err}</span></div>}
    <div className="filters"><label>From<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label></div>
    <div className="stats-grid">{cards.map(([l, v, I, sub]) => <div className="stat-card" key={l}><div className="stat-top"><span>{l}</span><div className="stat-icon"><I size={18} /></div></div><strong>{v}</strong><div className="stat-foot"><small>{sub}</small></div></div>)}</div>
    {s && <div className="dashboard-grid"><div className="panel"><div className="panel-head"><div><h3>Billed vs collected</h3><p>Last 12 months from your invoices and payments</p></div></div>
      <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={s.monthly}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf0f5" /><XAxis dataKey="label" axisLine={false} tickLine={false} /><YAxis axisLine={false} tickLine={false} tickFormatter={v => '₹' + v / 1000 + 'k'} /><Tooltip formatter={v => inr(v)} />
        <Area type="monotone" dataKey="billed" stroke="#6558e8" fill="#6558e822" strokeWidth={2} /><Area type="monotone" dataKey="collected" stroke="#16b981" fill="#16b98122" strokeWidth={2} /></AreaChart></ResponsiveContainer></div></div>
      <div className="panel"><div className="panel-head"><div><h3>Invoice health</h3><p>Right now</p></div></div>
        <div className="health-number">{s.overdue_count} <small>overdue invoices</small></div>
        <div className="health-row"><span>Overdue amount</span><b>{inr(s.overdue_amount)}</b></div><div className="health-row"><span>Billed in range</span><b>{inr(s.billed_total)}</b></div>
        {Object.entries(s.subscriptions_by_status).map(([k, n]) => <div className="health-row" key={k}><span>{k} subscriptions</span><b>{n}</b></div>)}
        <button className="text-link" onClick={() => go('Reports')}>See overdue invoices →</button></div></div>}</>
}

function Reports() {
  const [tab, setTab] = useState('invoices'); const [f, setF] = useState({ status: '', overdue_only: false, date_from: '', date_to: '', q: '', method: '' })
  const [rows, setRows] = useState([]); const [total, setTotal] = useState(0); const [offset, setOffset] = useState(0); const [err, setErr] = useState('')
  const q = useDebounced(f.q)
  useEffect(() => setOffset(0), [tab, f.status, f.overdue_only, f.date_from, f.date_to, q, f.method])
  useEffect(() => {
    const p = new URLSearchParams({ limit: PAGE, offset })
    if (tab !== 'payments' && f.status) p.set('status', f.status)
    if (tab === 'invoices' && f.overdue_only) p.set('overdue_only', 'true')
    if (tab !== 'subscriptions') { if (f.date_from) p.set('date_from', f.date_from); if (f.date_to) p.set('date_to', f.date_to) }
    if (tab !== 'payments' && q) p.set('q', q)
    if (tab === 'payments' && f.method) p.set('method', f.method)
    setErr(''); api(`/api/reports/${tab}?${p}`).then(d => { setRows(d.items); setTotal(d.total) }).catch(e => setErr(e.message))
  }, [tab, offset, f.status, f.overdue_only, f.date_from, f.date_to, q, f.method])
  const cols = rows[0] ? Object.keys(rows[0]).filter(k => k !== 'id') : []
  const statuses = tab === 'invoices' ? ['draft', 'confirmed', 'paid', 'overdue', 'cancelled'] : ['draft', 'quotation', 'confirmed', 'active', 'paused', 'closed']
  return <><div className="tabs">{['invoices', 'subscriptions', 'payments'].map(t => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t}</button>)}</div>
    <div className="filters">
      {tab !== 'payments' && <label>Search<input value={f.q} onChange={e => setF({ ...f, q: e.target.value })} placeholder="number or customer" /></label>}
      {tab !== 'payments' && <label>Status<select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="">All</option>{statuses.map(s => <option key={s}>{s}</option>)}</select></label>}
      {tab === 'payments' && <label>Method<select value={f.method} onChange={e => setF({ ...f, method: e.target.value })}><option value="">All</option>{ENUMS.method.map(s => <option key={s}>{s}</option>)}</select></label>}
      {tab !== 'subscriptions' && <><label>From<input type="date" value={f.date_from} onChange={e => setF({ ...f, date_from: e.target.value })} /></label><label>To<input type="date" value={f.date_to} onChange={e => setF({ ...f, date_to: e.target.value })} /></label></>}
      {tab === 'invoices' && <label className="check"><input type="checkbox" checked={f.overdue_only} onChange={e => setF({ ...f, overdue_only: e.target.checked })} /> Overdue only</label>}
      <button className="btn secondary" onClick={() => toCsv(rows, tab)}><Download size={15} /> Export page</button></div>
    {err && <div className="alert"><span>{err}</span></div>}
    <div className="panel table-panel"><div className="table-scroll"><table><thead><tr>{cols.map(c => <th key={c}>{label(c)}</th>)}</tr></thead>
      <tbody>{rows.map(r => <tr key={r.id}>{cols.map(c => <td key={c}><Cell c={c} v={r[c]} /></td>)}</tr>)}</tbody></table>{!rows.length && <div className="empty"><b>No records match these filters</b></div>}</div>
      <div className="table-toolbar"><Pager total={total} offset={offset} setOffset={setOffset} /></div></div></>
}

/* ------------------------------------------------------------------ generic resource page with workflow actions */
function ResourcePage({ page, user, notify }) {
  const R = RESOURCES[page]
  const [rows, setRows] = useState([]); const [total, setTotal] = useState(0); const [offset, setOffset] = useState(0); const [query, setQuery] = useState(''); const q = useDebounced(query)
  const [err, setErr] = useState(''); const [modal, setModal] = useState(null); const [form, setForm] = useState({})
  useEffect(() => setOffset(0), [page, q])
  const load = useCallback(() => {
    setErr(''); api(`/api/resources/${R.path}?limit=${PAGE}&offset=${offset}${q ? '&q=' + encodeURIComponent(q) : ''}`).then(d => { setRows(d.items); setTotal(d.total) }).catch(e => setErr(e.message))
  }, [R.path, offset, q])
  useEffect(() => { load() }, [load])
  const canWrite = !R.admin || user.role === 'admin'
  const run = async (fn, ok) => { try { await fn(); notify(ok); load() } catch (e) { setErr(e.message) } }
  const post = (path, body) => api(path, { method: 'POST', body: body || {} })

  const openCreate = () => { setForm(R.custom === 'payment' ? { method: 'bank_transfer' } : {}); setModal(R.custom === 'payment' ? 'payment' : 'create') }
  const create = e => { e.preventDefault(); const body = { ...form }; if (R.flags) R.flags.forEach(k => { if (body[k] === undefined) body[k] = true })
    run(async () => { await api(R.create || `/api/resources/${R.path}`, { method: 'POST', body }); setModal(null) }, page + ' saved') }
  const savePayment = e => { e.preventDefault()
    const ids = String(form.invoice_ids || '').split(',').map(s => s.trim()).filter(Boolean).map(Number)
    run(async () => { await post('/api/payments', { customer_id: Number(form.customer_id), amount: Number(form.amount), method: form.method, transaction_date: form.transaction_date || null, notes: form.notes || null, allocations: ids.map(invoice_id => ({ invoice_id })) }); setModal(null) }, 'Payment recorded') }

  const actions = row => {
    const b = (txt, fn, ok) => <button key={txt} className="btn secondary small" onClick={() => run(fn, ok)}>{txt}</button>
    if (page === 'Invoices') return [<button key="pdf" className="btn secondary small" onClick={() => openPdf(row.id).catch(e => setErr(e.message))}>PDF</button>,
      row.status === 'draft' && b('Confirm', () => post(`/api/invoices/${row.id}/confirm`), 'Invoice confirmed'),
      ['confirmed', 'overdue', 'paid'].includes(row.status) && b('Send', () => post(`/api/invoices/${row.id}/send`), 'Invoice emailed'),
      ['confirmed', 'overdue'].includes(row.status) && <button key="pay" className="btn secondary small" onClick={() => { setForm({ customer_id: row.customer_id, amount: row.amount_due, method: 'bank_transfer', invoice_ids: String(row.id) }); setModal('payment') }}>Pay</button>,
      ['draft', 'confirmed', 'overdue'].includes(row.status) && Number(row.amount_paid) === 0 && b('Cancel', () => post(`/api/invoices/${row.id}/cancel`, { reason: 'Cancelled by staff' }), 'Invoice cancelled')]
    if (page === 'Subscriptions') return [...(SUB_ACTIONS[row.status] || []).map(a => b(label(a), () => post(`/api/subscriptions/${row.id}/transition`, { action: a }), 'Subscription ' + label(a) + ' done')),
      ['draft', 'quotation', 'confirmed'].includes(row.status) && <button key="line" className="btn secondary small" onClick={() => { setForm({ subscription_id: row.id, quantity: 1 }); setModal('line') }}>Add line</button>]
    if (page === 'Quotations') return [...(QUOTE_ACTIONS[row.status] || []).map(([s, t]) => b(t, () => post(`/api/quotations/${row.id}/status`, { status: s }), 'Quotation ' + s)),
      row.status === 'approved' && b('Convert', () => post(`/api/quotations/${row.id}/convert`), 'Converted to a confirmed subscription')]
    if (R.path && canWrite && ['Customers', 'Products', 'Variants', 'Plans', 'Discounts', 'Staff'].includes(page) && 'is_active' in row)
      return [b(row.is_active ? 'Deactivate' : 'Activate', () => api(`/api/resources/${R.path}/${row.id}`, { method: 'PATCH', body: { is_active: !row.is_active } }), 'Updated')]
    return []
  }

  return <><div className="page-heading"><div><div className="eyebrow">BRIGHTLOOP WORKSPACE</div><h1>{page}</h1></div>
    <div className="heading-actions"><button className="btn secondary" onClick={load}><RefreshCw size={16} /> Refresh</button>
      {page === 'Subscriptions' && <button className="btn secondary" onClick={() => { const d = window.prompt('Billing run date (YYYY-MM-DD), blank = today'); if (d !== null) run(async () => { const r = await post('/api/billing/run' + (d ? '?run_date=' + d : '')); notify(`Billing run: ${r.invoices_created} created, ${r.invoices_skipped} skipped, ${r.error_count} errors`) }, 'Billing run finished') }}>Run billing</button>}
      {page === 'Invoices' && <button className="btn secondary" onClick={() => run(() => post('/api/invoices/mark-overdue'), 'Overdue sweep done')}>Mark overdue</button>}
      {!R.noCreate && canWrite && <button className="btn primary" onClick={openCreate}><Plus size={17} /> {R.newLabel || 'New ' + page.replace(/s$/, '')}</button>}</div></div>
    {err && <div className="alert"><span>{err}</span><button onClick={() => setErr('')}>×</button></div>}
    <div className="panel table-panel"><div className="table-toolbar"><div className="searchbox"><Search size={16} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder={`Search ${page.toLowerCase()}…`} /></div>
      <div className="toolbar-actions"><button className="btn secondary" onClick={() => toCsv(rows, page.toLowerCase())}><Download size={15} /> Export page</button></div></div>
      <div className="table-scroll"><table><thead><tr>{R.cols.map(c => <th key={c}>{label(c)}</th>)}<th /></tr></thead>
        <tbody>{rows.map(r => <tr key={r.id}>{R.cols.map(c => <td key={c}><Cell c={c} v={r[c]} /></td>)}<td className="row-actions">{actions(r)}</td></tr>)}</tbody></table>
        {!rows.length && <div className="empty"><b>No records to display</b></div>}</div>
      <div className="table-toolbar"><Pager total={total} offset={offset} setOffset={setOffset} /></div></div>

    {modal === 'create' && <Modal title={(R.newLabel || 'New ' + page.replace(/s$/, ''))} onClose={() => setModal(null)} onSubmit={create}>
      <div className="form-grid">{R.fields.map(f => <Field key={f} f={f} form={form} setForm={setForm} required={(R.required || []).includes(f)} />)}</div>
      {R.flags && <div className="flags">{R.flags.map(k => <label key={k} className="check"><input type="checkbox" checked={form[k] ?? true} onChange={e => setForm({ ...form, [k]: e.target.checked })} /> {label(k)}</label>)}</div>}</Modal>}
    {modal === 'payment' && <Modal title="Record payment" submit="Record payment" onClose={() => setModal(null)} onSubmit={savePayment}>
      <div className="form-grid"><Field f="customer_id" form={form} setForm={setForm} required /><Field f="amount" form={form} setForm={setForm} required /><Field f="method" form={form} setForm={setForm} required />
        <Field f="transaction_date" form={form} setForm={setForm} /><label className="wide">Invoice id(s) to settle (comma separated)<input value={form.invoice_ids || ''} onChange={e => setForm({ ...form, invoice_ids: e.target.value })} /></label>
        <label className="wide">Note<input value={form.notes || ''} onChange={e => setForm({ ...form, notes: e.target.value })} /></label></div></Modal>}
    {modal === 'line' && <Modal title="Add subscription line" onClose={() => setModal(null)} onSubmit={e => { e.preventDefault(); run(async () => { await post(`/api/subscriptions/${form.subscription_id}/lines`, { product_id: Number(form.product_id), variant_id: form.variant_id ? Number(form.variant_id) : null, quantity: Number(form.quantity) }); setModal(null) }, 'Line added') }}>
      <div className="form-grid"><Field f="product_id" form={form} setForm={setForm} required /><label>variant id<input type="number" value={form.variant_id || ''} onChange={e => setForm({ ...form, variant_id: e.target.value })} /></label>
        <label>quantity *<input type="number" min="1" required value={form.quantity || ''} onChange={e => setForm({ ...form, quantity: e.target.value })} /></label></div></Modal>}</>
}

/* ------------------------------------------------------------------ shell */
function StaffApp({ user, logout }) {
  const [page, setPage] = useState('Dashboard'); const [collapsed, setCollapsed] = useState(false); const [toast, setToast] = useState('')
  const notify = s => { setToast(s); setTimeout(() => setToast(''), 3500) }
  const nav = NAV.map(([g, items]) => [g, items.filter(([n]) => user.role === 'admin' || !RESOURCES[n]?.admin || ['Products', 'Variants', 'Plans', 'Discounts'].includes(n))]).filter(([g, items]) => items.length && (g !== 'Administration' || user.role === 'admin'))
  const hour = new Date().getHours(); const greet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).toUpperCase()
  const icon = Object.fromEntries(NAV.flatMap(([, i]) => i))
  return <div className="shell"><aside className={collapsed ? 'sidebar compact' : 'sidebar'}>
    <div className="brand"><div className="brand-mark">b</div>{!collapsed && <div><b>brightloop</b><small>SUBSCRIPTION OS</small></div>}</div>
    {nav.map(([group, items]) => <section className="nav-group" key={group}>{!collapsed && <div className="nav-label">{group}</div>}
      {items.map(([name, Icon]) => <button key={name} onClick={() => setPage(name)} className={'nav-item ' + (page === name ? 'selected' : '')} title={name}><Icon size={18} />{!collapsed && <span>{name}</span>}</button>)}</section>)}
    <div className="sidebar-bottom"><div className="profile"><div className="avatar">{user.full_name.split(' ').map(w => w[0]).slice(0, 2).join('')}</div>
      {!collapsed && <span><b>{user.full_name}</b><small>{user.role === 'admin' ? 'Administrator' : 'Staff'}</small></span>}<button className="icon-btn" title="Sign out" onClick={logout}><LogOut size={17} /></button></div></div></aside>
    <main className="main"><header className="topbar"><div className="top-left"><button className="icon-btn" onClick={() => setCollapsed(!collapsed)}><Menu size={19} /></button><span className="crumb">Workspace</span><span className="slash">/</span><b>{page}</b></div></header>
      <div className="content">
        {page === 'Dashboard' && <><div className="page-heading"><div><div className="eyebrow">{today}</div><h1>{greet}, {user.full_name.split(' ')[0]}</h1><p>Here’s what’s happening with your subscriptions.</p></div></div><Dashboard go={setPage} /></>}
        {page === 'Reports' && <><div className="page-heading"><div><div className="eyebrow">FINANCE</div><h1>Reports</h1><p>Active subscriptions, payments and overdue invoices with filters.</p></div></div><Reports /></>}
        {RESOURCES[page] && <ResourcePage key={page} page={page} user={user} notify={notify} />}
        <div className="footer"><span>© {new Date().getFullYear()} Brightloop Software</span><a href={API + '/docs'} target="_blank" rel="noreferrer">API documentation ↗</a></div></div></main>
    {toast && <div className="toast">✓ {toast}</div>}</div>
}

function App() {
  const [user, setUser] = useState(null); const [ready, setReady] = useState(!token)
  const logout = useCallback(() => { token = ''; localStorage.removeItem('bl_token'); setUser(null) }, [])
  useEffect(() => { onUnauthorized = logout }, [logout])
  useEffect(() => { if (token) api('/api/auth/me').then(setUser).catch(() => {}).finally(() => setReady(true)) }, [])
  if (!ready) return <div className="empty">Loading…</div>
  if (!user) return <AuthScreen onAuthed={setUser} />
  return user.role === 'customer' ? <Portal user={user} logout={logout} /> : <StaffApp user={user} logout={logout} />
}
createRoot(document.getElementById('root')).render(<App />)
