function formatNumber(value, suffix = '') {
  if (value === null || value === undefined || value === '') {
    return '--';
  }
  const numeric = Number(value);
  if (Number.isNaN(numeric)) {
    return String(value);
  }
  return `${numeric.toFixed(1)}${suffix}`;
}

function formatUptime(seconds) {
  const numeric = Number(seconds);
  if (!Number.isFinite(numeric)) {
    return '--';
  }
  const hrs = Math.floor(numeric / 3600);
  const mins = Math.floor((numeric % 3600) / 60);
  return `${hrs}h ${mins}m`;
}

export default function StatusCard({ status, connected, loading }) {
  const services = Object.entries(status.services || {});
  const nowPlaying = status.media || status.player?.item;

  return (
    <section className="rounded-2xl border border-slate-700/70 bg-slate-800/60 p-6 shadow-lg">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-slate-400">
          Status
        </h2>
        <span className="text-xs text-slate-500">
          {loading ? 'Waiting for device…' : connected ? 'Live updates' : 'Offline'}
        </span>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-4 text-sm text-slate-200">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Uptime</p>
          <p className="mt-2 text-lg font-semibold text-emerald-300">
            {formatUptime(status.uptime)}
          </p>
        </div>
        <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-4 text-sm text-slate-200">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">CPU</p>
          <p className="mt-2 text-lg font-semibold text-emerald-300">
            {formatNumber(status.cpu, '%')}
          </p>
        </div>
        <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-4 text-sm text-slate-200">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Memory</p>
          <p className="mt-2 text-lg font-semibold text-emerald-300">
            {formatNumber(status.mem, '%')}
          </p>
        </div>
        <div className="rounded-xl border border-slate-700/50 bg-slate-900/50 p-4 text-sm text-slate-200">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Temperature</p>
          <p className="mt-2 text-lg font-semibold text-emerald-300">
            {formatNumber(status.temp, '°C')}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Active Mode</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">{status.mode}</p>
          <p className="mt-1 break-words text-xs text-slate-400">
            {status.url || 'No URL configured'}
          </p>
          {nowPlaying && (
            <div className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-xs text-emerald-200">
              <p className="uppercase tracking-[0.3em] text-emerald-400">Now Playing</p>
              <p className="mt-1 font-medium text-emerald-100">
                {nowPlaying.name || nowPlaying.identifier || nowPlaying}
              </p>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Services</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {services.length === 0 ? (
              <span className="text-slate-500">No service data yet.</span>
            ) : (
              services.map(([name, service]) => (
                <span
                  key={name}
                  className={`rounded-full border px-3 py-1 ${
                    service.status === 'running'
                      ? 'border-emerald-500/50 text-emerald-200'
                      : service.status === 'error'
                      ? 'border-red-500/60 text-red-300'
                      : 'border-slate-600/60 text-slate-300'
                  }`}
                >
                  {name}: {service.status}
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
