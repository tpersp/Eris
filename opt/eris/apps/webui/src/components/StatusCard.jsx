function formatNumber(value, suffix) {
  if (value === null || value === undefined || value === '') {
    return '--';
  }

  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return String(value);
  }

  return `${numeric.toFixed(1)}${suffix ?? ''}`;
}

export default function StatusCard({ status, connected, loading }) {
  const statusItems = [
    {
      label: 'Uptime',
      value: status.uptime ?? '--'
    },
    {
      label: 'CPU',
      value: formatNumber(status.cpu, '%')
    },
    {
      label: 'Memory',
      value: formatNumber(status.mem, '%')
    },
    {
      label: 'Temperature',
      value: formatNumber(status.temp, '°C')
    }
  ];

  const activeUrl =
    status.active_url && status.active_url !== '--' ? status.active_url : null;

  return (
    <section className="rounded-2xl border border-slate-700/70 bg-slate-800/60 p-6 shadow-lg">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-slate-400">
          Status
        </h2>
        <span className="text-xs text-slate-500">
          {loading
            ? 'Waiting for device…'
            : connected
            ? 'Live updates'
            : 'Offline'}
        </span>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statusItems.map((item) => (
          <div
            key={item.label}
            className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-4 text-sm text-slate-200"
          >
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
              {item.label}
            </p>
            <p className="mt-2 text-lg font-semibold text-neon">{item.value}</p>
          </div>
        ))}
      </div>
      <div className="mt-6 rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">
          Active URL
        </p>
        <p className="mt-2 break-words text-sm text-slate-200">
          {activeUrl ?? '—'}
        </p>
      </div>
    </section>
  );
}
