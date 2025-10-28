export default function Header({ connected }) {
  return (
    <header className="flex flex-col gap-2 rounded-2xl border border-slate-700/70 bg-slate-800/60 p-6 shadow-lg md:flex-row md:items-center md:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
          Eris Control
        </h1>
        <p className="text-sm text-slate-400">
          Controlled chaos for beautiful screens.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-medium ${
            connected
              ? 'border-emerald-500/70 bg-emerald-500/20 text-emerald-200'
              : 'border-amber-500/70 bg-amber-500/20 text-amber-200'
          }`}
        >
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              connected ? 'bg-emerald-300' : 'bg-amber-300'
            }`}
          />
          {connected ? 'Online' : 'Reconnecting'}
        </span>
      </div>
    </header>
  );
}
