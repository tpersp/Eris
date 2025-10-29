import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApi } from '../hooks/useApi.js';

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

function emptyPlaylistForm() {
  return {
    id: '',
    name: '',
    loop: true,
    items: []
  };
}

function emptyScheduleForm() {
  return {
    id: '',
    playlistId: '',
    start: '08:00',
    end: '18:00',
    days: new Set(['mon', 'tue', 'wed', 'thu', 'fri'])
  };
}

export default function Scheduler() {
  const { request } = useApi();
  const [playlists, setPlaylists] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [mediaItems, setMediaItems] = useState([]);
  const [fallback, setFallback] = useState({ mode: 'web', url: '', playlist_id: null });
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [playlistForm, setPlaylistForm] = useState(emptyPlaylistForm);
  const [scheduleForm, setScheduleForm] = useState(emptyScheduleForm);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mediaResponse, playlistsResponse, schedulesResponse, schedulerStatus] = await Promise.all([
        request('/api/media'),
        request('/api/playlists'),
        request('/api/schedules'),
        request('/api/scheduler/status')
      ]);
      setMediaItems(mediaResponse?.items ?? []);
      setPlaylists(playlistsResponse?.playlists ?? []);
      setSchedules(schedulesResponse?.schedules ?? []);
      setFallback(schedulerStatus?.fallback ?? { mode: 'web', url: '', playlist_id: null });
      setStatus(schedulerStatus?.scheduler ?? null);
    } catch (err) {
      setError(err.message || 'Unable to load scheduler data');
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const mediaOptions = useMemo(
    () => mediaItems.map((item) => ({ value: item.identifier, label: `${item.name} (${item.media_type})` })),
    [mediaItems]
  );

  const addPlaylistItem = () => {
    setPlaylistForm((prev) => ({
      ...prev,
      items: [...prev.items, { mediaId: '', duration: '' }]
    }));
  };

  const updatePlaylistItem = (index, patch) => {
    setPlaylistForm((prev) => ({
      ...prev,
      items: prev.items.map((item, idx) => (idx === index ? { ...item, ...patch } : item))
    }));
  };

  const removePlaylistItem = (index) => {
    setPlaylistForm((prev) => ({
      ...prev,
      items: prev.items.filter((_, idx) => idx !== index)
    }));
  };

  const submitPlaylist = async (event) => {
    event.preventDefault();
    setError(null);

    if (!playlistForm.id || !playlistForm.name) {
      setError('Playlist id and name are required.');
      return;
    }

    const payload = {
      id: playlistForm.id,
      name: playlistForm.name,
      loop: playlistForm.loop,
      items: playlistForm.items
        .filter((item) => item.mediaId)
        .map((item) => ({
          media_id: item.mediaId,
          ...(item.duration ? { duration: Number(item.duration) } : {})
        }))
    };

    try {
      await request('/api/playlists', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      setPlaylistForm(emptyPlaylistForm);
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to save playlist');
    }
  };

  const deletePlaylist = async (playlistId) => {
    try {
      await request(`/api/playlists/${playlistId}`, { method: 'DELETE' });
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to delete playlist');
    }
  };

  const toggleDay = (day) => {
    setScheduleForm((prev) => {
      const days = new Set(prev.days);
      if (days.has(day)) {
        days.delete(day);
      } else {
        days.add(day);
      }
      return { ...prev, days };
    });
  };

  const submitSchedule = async (event) => {
    event.preventDefault();
    if (!scheduleForm.id || !scheduleForm.playlistId) {
      setError('Schedule id and playlist are required.');
      return;
    }

    const payload = {
      id: scheduleForm.id,
      playlist_id: scheduleForm.playlistId,
      start: scheduleForm.start,
      end: scheduleForm.end,
      days: Array.from(scheduleForm.days)
    };

    try {
      await request('/api/schedules', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      setScheduleForm(emptyScheduleForm);
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to save schedule');
    }
  };

  const deleteSchedule = async (scheduleId) => {
    try {
      await request(`/api/schedules/${scheduleId}`, { method: 'DELETE' });
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to delete schedule');
    }
  };

  const updateFallback = async (event) => {
    event.preventDefault();
    try {
      await request('/api/scheduler/fallback', {
        method: 'POST',
        body: JSON.stringify(fallback)
      });
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to update fallback');
    }
  };

  return (
    <div className="space-y-8">
      {error && (
        <div className="rounded-lg border border-red-500/60 bg-red-900/20 px-4 py-3 text-sm text-red-100">
          {error}
        </div>
      )}

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Scheduler Status</h2>
        {loading ? (
          <p className="mt-2 text-sm text-slate-400">Loading scheduler metrics…</p>
        ) : (
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Active</p>
              <p className="mt-2 text-lg font-semibold text-emerald-300">
                {status?.active ? 'Yes' : 'No'}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Playlist</p>
              <p className="mt-2 text-lg font-semibold text-slate-100">
                {status?.playlist_id || '—'}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4">
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Schedule</p>
              <p className="mt-2 text-lg font-semibold text-slate-100">
                {status?.schedule_id || '—'}
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Create Playlist</h2>
        <form className="mt-4 space-y-4" onSubmit={submitPlaylist}>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Playlist ID</label>
              <input
                value={playlistForm.id}
                onChange={(event) => setPlaylistForm((prev) => ({ ...prev, id: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Name</label>
              <input
                value={playlistForm.name}
                onChange={(event) => setPlaylistForm((prev) => ({ ...prev, name: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={playlistForm.loop}
              onChange={(event) => setPlaylistForm((prev) => ({ ...prev, loop: event.target.checked }))}
              className="rounded border-slate-600 bg-slate-900"
            />
            Loop playlist
          </label>
          <div className="space-y-3">
            {playlistForm.items.map((item, index) => (
              <div key={index} className="grid gap-3 rounded-xl border border-slate-800/70 bg-slate-950/60 p-4 md:grid-cols-3">
                <div className="md:col-span-2">
                  <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Media Item</label>
                  <select
                    value={item.mediaId}
                    onChange={(event) => updatePlaylistItem(index, { mediaId: event.target.value })}
                    className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                    required
                  >
                    <option value="">Select media…</option>
                    {mediaOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Duration (seconds)</label>
                  <input
                    type="number"
                    min="0"
                    value={item.duration}
                    onChange={(event) => updatePlaylistItem(index, { duration: event.target.value })}
                    className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                    placeholder="Auto"
                  />
                </div>
                <div className="md:col-span-3 text-right">
                  <button
                    type="button"
                    onClick={() => removePlaylistItem(index)}
                    className="rounded-md border border-red-500/50 px-2 py-1 text-xs text-red-300 transition hover:border-red-400 hover:text-red-200"
                  >
                    Remove item
                  </button>
                </div>
              </div>
            ))}
            <button
              type="button"
              onClick={addPlaylistItem}
              className="rounded-lg border border-emerald-400/60 px-3 py-2 text-sm text-emerald-200 transition hover:bg-emerald-500/10"
            >
              Add Media Item
            </button>
          </div>
          <div className="text-right">
            <button
              type="submit"
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 shadow-lg transition hover:bg-emerald-400"
            >
              Save Playlist
            </button>
          </div>
        </form>
      </section>

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-emerald-200">Existing Playlists</h2>
          <button
            onClick={loadData}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs uppercase tracking-[0.3em] text-slate-300 transition hover:border-emerald-400/60 hover:text-emerald-200"
          >
            Refresh
          </button>
        </div>
        <div className="mt-4 space-y-4">
          {playlists.length === 0 ? (
            <p className="text-sm text-slate-500">No playlists defined yet.</p>
          ) : (
            playlists.map((playlist) => (
              <div key={playlist.id} className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">{playlist.name}</h3>
                    <p className="text-xs text-slate-500">ID: {playlist.id}</p>
                  </div>
                  <button
                    onClick={() => deletePlaylist(playlist.id)}
                    className="rounded-md border border-red-500/50 px-2 py-1 text-xs text-red-300 transition hover:border-red-400 hover:text-red-200"
                  >
                    Delete
                  </button>
                </div>
                <ul className="mt-3 space-y-2 text-sm text-slate-300">
                  {playlist.items?.map((item, index) => (
                    <li key={`${item.media_id}-${index}`} className="rounded-lg bg-slate-900/70 px-3 py-2">
                      <div className="font-medium text-slate-100">{item.media_id}</div>
                      <div className="text-xs text-slate-500">
                        Duration: {item.duration ? `${item.duration} s` : 'Auto'}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Create Schedule</h2>
        <form className="mt-4 space-y-4" onSubmit={submitSchedule}>
          <div className="grid gap-4 md:grid-cols-4">
            <div>
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Schedule ID</label>
              <input
                value={scheduleForm.id}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, id: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Playlist</label>
              <select
                value={scheduleForm.playlistId}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, playlistId: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                required
              >
                <option value="">Select playlist…</option>
                {playlists.map((playlist) => (
                  <option key={playlist.id} value={playlist.id}>
                    {playlist.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Start</label>
                <input
                  type="time"
                  value={scheduleForm.start}
                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, start: event.target.value }))}
                  className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.3em] text-slate-500">End</label>
                <input
                  type="time"
                  value={scheduleForm.end}
                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, end: event.target.value }))}
                  className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
                />
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            {DAYS.map((day) => (
              <label key={day} className="inline-flex items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={scheduleForm.days.has(day)}
                  onChange={() => toggleDay(day)}
                />
                {day.toUpperCase()}
              </label>
            ))}
          </div>
          <div className="text-right">
            <button
              type="submit"
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 shadow-lg transition hover:bg-emerald-400"
            >
              Save Schedule
            </button>
          </div>
        </form>
      </section>

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Existing Schedules</h2>
        <div className="mt-4 space-y-4">
          {schedules.length === 0 ? (
            <p className="text-sm text-slate-500">No schedules defined.</p>
          ) : (
            schedules.map((schedule) => (
              <div key={schedule.id} className="rounded-xl border border-slate-800/70 bg-slate-950/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">{schedule.id}</h3>
                    <p className="text-xs text-slate-500">Playlist: {schedule.playlist_id}</p>
                  </div>
                  <button
                    onClick={() => deleteSchedule(schedule.id)}
                    className="rounded-md border border-red-500/50 px-2 py-1 text-xs text-red-300 transition hover:border-red-400 hover:text-red-200"
                  >
                    Delete
                  </button>
                </div>
                <div className="mt-2 text-xs text-slate-400">
                  {schedule.start} → {schedule.end} ({(schedule.days || []).join(', ') || 'all days'})
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800/70 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Fallback Behaviour</h2>
        <form className="mt-4 space-y-4" onSubmit={updateFallback}>
          <div className="flex gap-4">
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="fallback-mode"
                value="web"
                checked={fallback.mode === 'web'}
                onChange={() => setFallback((prev) => ({ ...prev, mode: 'web', playlist_id: null }))}
              />
              Web URL
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="fallback-mode"
                value="playlist"
                checked={fallback.mode === 'playlist'}
                onChange={() => setFallback((prev) => ({ ...prev, mode: 'playlist', url: prev.url || '' }))}
              />
              Playlist
            </label>
          </div>
          {fallback.mode === 'web' ? (
            <div>
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">URL</label>
              <input
                value={fallback.url ?? ''}
                onChange={(event) => setFallback((prev) => ({ ...prev, url: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </div>
          ) : (
            <div>
              <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Playlist</label>
              <select
                value={fallback.playlist_id ?? ''}
                onChange={(event) => setFallback((prev) => ({ ...prev, playlist_id: event.target.value }))}
                className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              >
                <option value="">Select playlist…</option>
                {playlists.map((playlist) => (
                  <option key={playlist.id} value={playlist.id}>
                    {playlist.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="text-right">
            <button
              type="submit"
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-900 shadow-lg transition hover:bg-emerald-400"
            >
              Save Fallback
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
