import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { usePrioritizedSpending, useRefreshPrioritizedSpending, useAllSpendingEntries, useSpendingVendors, useSpendingPeople, useConnectors } from '../api/hooks';
import type { SpendingTransaction, SpendingEntry } from '../api/types';
import { TimeAgo } from '../components/shared/TimeAgo';
import { PrioritizedSourceList, ScoreBadge } from '../components/shared/PrioritizedSourceList';
import { MultiSelectDropdown } from '../components/shared/MultiSelectDropdown';
import { openExternal } from '../api/client';

function formatAmount(amount: number, currency: string = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function billStatusBadge(status: string, paymentStatus: string) {
  const s = (paymentStatus || status || '').toUpperCase();
  const cls = s.includes('PAID') || s.includes('COMPLETED')
    ? 'priority-urgency-low'
    : s.includes('ERROR') || s.includes('FAIL')
    ? 'priority-urgency-high'
    : s.includes('PENDING') || s.includes('APPROVAL')
    ? 'priority-urgency-medium'
    : 'priority-urgency-low';
  const label = s.replace(/_/g, ' ') || 'UNKNOWN';
  return <span className={`priority-score-badge ${cls}`} style={{ fontSize: '0.65rem', padding: '0 4px', borderRadius: '3px', width: 'auto', minWidth: 'unset', height: 'auto', lineHeight: '1.4' }}>{label}</span>;
}

function sourceBadge(source: string) {
  if (!source || source === 'ramp') return null;
  const label = source === 'lunchmoney' ? 'LunchMoney' : source;
  return (
    <span style={{
      fontFamily: 'var(--font-mono)',
      fontSize: '0.65rem',
      padding: '0 4px',
      border: '1px solid var(--color-border)',
      borderRadius: '3px',
      color: 'var(--color-text-muted)',
      marginLeft: '5px',
      verticalAlign: 'middle',
    }}>
      {label}
    </span>
  );
}

function typeLabel(transactionType: string) {
  return (
    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7em', opacity: 0.55 }}>
      {transactionType}
    </span>
  );
}

const TYPE_OPTIONS = [
  { value: '',           label: 'All types',       transaction_type: undefined as string | undefined, direction: undefined as string | undefined },
  { value: 'card',       label: 'Cards',            transaction_type: 'card',  direction: 'out' },
  { value: 'bill',       label: 'Bills / AP',       transaction_type: 'bill',  direction: 'out' },
  { value: 'po',         label: 'Purchase Orders',  transaction_type: 'po',    direction: 'out' },
  { value: 'receivable', label: 'Receivable',       transaction_type: undefined, direction: 'in' },
] as const;

export function SpendingPage() {
  const [days, setDays] = useState(7);
  const { data, isLoading } = usePrioritizedSpending(days, true);
  const refresh = useRefreshPrioritizedSpending(days, true);

  const [allSearchQ, setAllSearchQ] = useState('');
  const [allDateFrom, setAllDateFrom] = useState('');
  const [allDateTo, setAllDateTo] = useState('');
  const [allVendorFilter, setAllVendorFilter] = useState('');
  const [allVendorQ, setAllVendorQ] = useState('');
  const [allTypeFilter, setAllTypeFilter] = useState('');
  const [allSourceFilter, setAllSourceFilter] = useState('');
  const [allPeopleFilter, setAllPeopleFilter] = useState<string[]>([]);
  const [allPeopleQ, setAllPeopleQ] = useState('');

  const { data: vendorData } = useSpendingVendors(allVendorQ || undefined);
  const { data: peopleData } = useSpendingPeople(allPeopleQ || undefined);
  const { data: connectors } = useConnectors();
  const hasLunchMoney = connectors?.some(c => c.id === 'lunchmoney' && c.enabled) ?? false;

  const typeOption = TYPE_OPTIONS.find(o => o.value === allTypeFilter) ?? TYPE_OPTIONS[0];

  const allQuery = useAllSpendingEntries({
    days: 365,
    q: allVendorFilter || allSearchQ || undefined,
    from_date: allDateFrom || undefined,
    to_date: allDateTo || undefined,
    transaction_type: typeOption.transaction_type,
    direction: typeOption.direction,
    source: allSourceFilter || undefined,
    person: allPeopleFilter.length > 0 ? allPeopleFilter.join(',') : undefined,
  });
  const allEntries = useMemo(
    () => allQuery.data?.pages.flatMap(p => p.entries) ?? [],
    [allQuery.data]
  );
  const allTotal = allQuery.data?.pages[0]?.total_count ?? 0;

  const filterControls = (
    <>
      <label>
        Vendor
        <input
          type="search"
          list="spending-vendor-list"
          value={allVendorFilter}
          onChange={e => { setAllVendorFilter(e.target.value); setAllVendorQ(e.target.value); }}
          placeholder="All vendors"
          className="all-search-filter-input"
        />
        <datalist id="spending-vendor-list">
          {vendorData?.vendors.map(v => <option key={v} value={v} />)}
        </datalist>
      </label>
      <label>
        Type
        <select
          value={allTypeFilter}
          onChange={e => setAllTypeFilter(e.target.value)}
          className="all-search-filter-input"
        >
          {TYPE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </label>
      <MultiSelectDropdown
        label="People"
        options={peopleData?.people ?? []}
        selected={allPeopleFilter}
        onChange={setAllPeopleFilter}
        searchPlaceholder="Search people..."
        onSearchChange={setAllPeopleQ}
      />
      {hasLunchMoney && (
        <label>
          Source
          <select
            value={allSourceFilter}
            onChange={e => setAllSourceFilter(e.target.value)}
            className="all-search-filter-input"
          >
            <option value="">All sources</option>
            <option value="ramp">Ramp</option>
            <option value="lunchmoney">LunchMoney</option>
          </select>
        </label>
      )}
    </>
  );

  return (
    <PrioritizedSourceList
      title="Finance"
      source="ramp"
      items={(data?.items ?? []) as SpendingTransaction[]}
      isLoading={isLoading}
      error={data?.error}
      stale={data?.stale}
      refresh={refresh}
      days={days}
      onDaysChange={setDays}
      dayOptions={[7, 30, 90, 180, 365]}
      itemNoun="transaction"
      getIssueTitle={(t) => `${t.merchant_name} — ${formatAmount(t.amount, t.currency)}`}
      onOpen={(t) => { if (t.ramp_url) openExternal(t.ramp_url); }}
      errorMessage={
        <p className="empty-state">
          No finance connectors connected. Add Ramp or LunchMoney credentials in{' '}
          <Link to="/settings">Settings</Link>.
        </p>
      }
      renderItem={(txn, expanded) => (
        <div
          className="dashboard-item dashboard-item-link"
          style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: txn.ramp_url ? 'pointer' : 'default' }}
          onClick={() => { if (txn.ramp_url) openExternal(txn.ramp_url); }}
        >
          <div style={{ flexShrink: 0, paddingTop: '2px' }}>
            <ScoreBadge score={txn.priority_score} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="dashboard-item-title">
              <strong className="ramp-amount">{formatAmount(txn.amount, txn.currency)}</strong>
              {' '}{txn.merchant_name || 'Unknown'}
              {sourceBadge(txn.source)}
            </div>
            <div className="dashboard-item-meta">
              {txn.cardholder_name && <>{txn.cardholder_name} &middot; </>}
              {txn.category && <>{txn.category} &middot; </>}
              <TimeAgo date={txn.transaction_date} />
            </div>
            {txn.priority_reason && (
              <div className="dashboard-item-meta" style={{ fontStyle: 'italic' }}>{txn.priority_reason}</div>
            )}
            {expanded && txn.memo && (
              <div className="dashboard-item-expanded">{txn.memo}</div>
            )}
          </div>
        </div>
      )}
      allTab={{
        items: allEntries,
        total: allTotal,
        isLoading: allQuery.isLoading,
        hasNextPage: !!allQuery.hasNextPage,
        isFetchingNextPage: allQuery.isFetchingNextPage,
        fetchNextPage: allQuery.fetchNextPage,
        search: {
          hasDateFilter: true,
          extraFilters: filterControls,
          onParamsChange: ({ q, from_date, to_date }) => {
            setAllSearchQ(q ?? '');
            setAllDateFrom(from_date ?? '');
            setAllDateTo(to_date ?? '');
          },
        },
        renderItem: (item, expanded) => {
          const entry = item as SpendingEntry;
          const isCard = entry.transaction_type === 'card';
          return (
            <div
              className="dashboard-item dashboard-item-link"
              style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start', cursor: entry.external_url ? 'pointer' : 'default' }}
              onClick={() => { if (entry.external_url) openExternal(entry.external_url); }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="dashboard-item-title">
                  <strong className="ramp-amount">{formatAmount(entry.amount, entry.currency)}</strong>
                  {' '}{entry.vendor_name || 'Unknown'}
                  {!isCard && ' '}
                  {!isCard && billStatusBadge(entry.status || '', entry.payment_status || '')}
                  {sourceBadge(entry.source)}
                </div>
                <div className="dashboard-item-meta">
                  {typeLabel(entry.transaction_type)}
                  {' \u00b7 '}
                  <TimeAgo date={entry.entry_date} />
                  {entry.person_name && <> &middot; {entry.person_name}</>}
                  {!isCard && entry.invoice_number && <> &middot; #{entry.invoice_number}</>}
                </div>
                {expanded && entry.memo && (
                  <div className="dashboard-item-expanded">{entry.memo}</div>
                )}
              </div>
            </div>
          );
        },
      }}
    />
  );
}

export default SpendingPage;
