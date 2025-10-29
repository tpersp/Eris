import { useState } from 'react';

export default function UrlForm({ value, onChange, onSubmit, disabled }) {
  const [isSubmitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (disabled || isSubmitting) {
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit(value?.trim());
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-slate-700/70 bg-slate-800/60 p-6 shadow-lg"
    >
      <label
        htmlFor="eris-url-input"
        className="block text-sm font-medium text-slate-300"
      >
        Target URL
      </label>
      <div className="mt-3 flex flex-col gap-3 md:flex-row">
        <input
          id="eris-url-input"
          type="url"
          inputMode="url"
          placeholder="https://example.com"
          value={value ?? ''}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          className="w-full rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-3 text-slate-100 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-500/40 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || isSubmitting}
          className="inline-flex items-center justify-center rounded-xl bg-emerald-500 px-6 py-3 text-sm font-semibold text-slate-900 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isSubmitting ? 'Sending…' : 'Go'}
        </button>
      </div>
    </form>
  );
}
