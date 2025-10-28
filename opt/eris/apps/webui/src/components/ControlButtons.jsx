const baseButton =
  'flex-1 min-w-[120px] rounded-xl border border-slate-600/70 bg-slate-900/60 px-4 py-3 text-sm font-semibold text-slate-200 shadow transition hover:border-neon/70 hover:text-neon disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500';

export default function ControlButtons({
  disabled,
  onReload,
  onBack,
  onForward,
  onHome,
  onToggleBlank,
  isBlanked
}) {
  const controls = [
    { label: 'Reload', action: onReload },
    { label: 'Back', action: onBack },
    { label: 'Forward', action: onForward },
    { label: 'Home', action: onHome }
  ];

  return (
    <section className="rounded-2xl border border-slate-700/70 bg-slate-800/60 p-6 shadow-lg">
      <h2 className="text-sm font-medium uppercase tracking-[0.2em] text-slate-400">
        Controls
      </h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {controls.map((button) => (
          <button
            key={button.label}
            type="button"
            className={baseButton}
            disabled={disabled}
            onClick={button.action}
          >
            {button.label}
          </button>
        ))}
        <button
          type="button"
          className={`${baseButton} ${
            isBlanked
              ? 'border-amber-500/70 text-amber-300 hover:text-amber-200'
              : 'border-emerald-500/70 text-emerald-200 hover:text-emerald-100'
          }`}
          disabled={disabled}
          onClick={onToggleBlank}
        >
          {isBlanked ? 'Unblank' : 'Blank'}
        </button>
      </div>
    </section>
  );
}
