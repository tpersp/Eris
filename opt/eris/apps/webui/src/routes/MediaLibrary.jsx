import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApi } from '../hooks/useApi.js';

function splitIdentifier(identifier) {
  const [source, ...rest] = identifier.split(':');
  return { source, relative: rest.join(':') };
}

function encodePath(relative) {
  return relative
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) {
    return '--';
  }
  if (bytes === 0) {
    return '0 B';
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, index)).toFixed(1)} ${units[index]}`;
}

export default function MediaLibrary() {
  const { request } = useApi();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadFolder, setUploadFolder] = useState('');
  const [uploadTags, setUploadTags] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [tagInput, setTagInput] = useState('');
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request('/api/media');
      setItems(data?.items ?? []);
    } catch (err) {
      setError(err.message || 'Failed to load media');
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleUpload = async (event) => {
    event.preventDefault();
    if (!uploadFile) {
      setError('Choose a file to upload.');
      return;
    }

    setUploading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      if (uploadFolder) {
        formData.append('folder', uploadFolder);
      }
      if (uploadTags) {
        const tags = uploadTags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean);
        if (tags.length) {
          formData.append('tags', JSON.stringify(tags));
        }
      }
      await request('/api/media/upload', {
        method: 'POST',
        body: formData
      });
      setUploadFile(null);
      setUploadFolder('');
      setUploadTags('');
      await refresh();
    } catch (err) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (identifier) => {
    const { source, relative } = splitIdentifier(identifier);
    try {
      await request(`/api/media/${source}/${encodePath(relative)}`, {
        method: 'DELETE'
      });
      await refresh();
    } catch (err) {
      setError(err.message || 'Delete failed');
    }
  };

  const startTagEdit = (identifier, tags) => {
    setEditingId(identifier);
    setTagInput((tags || []).join(', '));
  };

  const saveTags = async (identifier) => {
    const { source, relative } = splitIdentifier(identifier);
    const tags = tagInput
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    try {
      await request(`/api/media/${source}/${encodePath(relative)}/tags`, {
        method: 'POST',
        body: JSON.stringify({ tags })
      });
      setEditingId(null);
      await refresh();
    } catch (err) {
      setError(err.message || 'Unable to update tags');
    }
  };

  const sortedItems = useMemo(
    () =>
      [...items].sort((a, b) => {
        const nameA = a.name.toLowerCase();
        const nameB = b.name.toLowerCase();
        return nameA.localeCompare(nameB);
      }),
    [items]
  );

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-emerald-200">Upload Media</h2>
        <p className="mt-1 text-sm text-slate-400">
          Files are stored in the local media library and become available for playlists.
        </p>
        <form className="mt-4 grid gap-4 md:grid-cols-2" onSubmit={handleUpload}>
          <div>
            <label className="text-xs uppercase tracking-[0.3em] text-slate-500">File</label>
            <input
              type="file"
              onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Folder (optional)</label>
            <input
              value={uploadFolder}
              onChange={(event) => setUploadFolder(event.target.value)}
              placeholder="e.g. promos"
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs uppercase tracking-[0.3em] text-slate-500">Tags</label>
            <input
              value={uploadTags}
              onChange={(event) => setUploadTags(event.target.value)}
              placeholder="brand, launch, summer"
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
            />
          </div>
          <div className="md:col-span-2 flex items-center justify-between">
            <p className="text-xs text-slate-500">Max upload size is defined by device configuration.</p>
            <button
              type="submit"
              disabled={uploading || !uploadFile}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 shadow-lg transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {uploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        </form>
      </section>

      {error && (
        <div className="rounded-lg border border-red-500/60 bg-red-900/20 px-4 py-3 text-sm text-red-100">
          {error}
        </div>
      )}

      <section className="rounded-2xl border border-slate-800/80 bg-slate-900/60 p-6 shadow-lg">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-emerald-200">Library</h2>
          <button
            onClick={refresh}
            className="rounded-lg border border-slate-700 px-3 py-1 text-xs uppercase tracking-[0.3em] text-slate-300 transition hover:border-emerald-400/70 hover:text-emerald-200"
          >
            Refresh
          </button>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-900/80 text-xs uppercase tracking-[0.3em] text-slate-400">
              <tr>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Source</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-right">Size</th>
                <th className="px-4 py-3 text-left">Tags</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 text-slate-300">
              {loading ? (
                <tr>
                  <td colSpan="6" className="px-4 py-6 text-center text-slate-500">
                    Loading media…
                  </td>
                </tr>
              ) : sortedItems.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-4 py-6 text-center text-slate-500">
                    No media available yet.
                  </td>
                </tr>
              ) : (
                sortedItems.map((item) => {
                  const isEditing = editingId === item.identifier;
                  return (
                    <tr key={item.identifier}>
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-100">{item.name}</div>
                        <div className="text-xs text-slate-500">{item.identifier}</div>
                      </td>
                      <td className="px-4 py-3 capitalize">{item.source}</td>
                      <td className="px-4 py-3 capitalize">{item.media_type}</td>
                      <td className="px-4 py-3 text-right text-slate-400">{formatBytes(item.size)}</td>
                      <td className="px-4 py-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <input
                              value={tagInput}
                              onChange={(event) => setTagInput(event.target.value)}
                              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs"
                            />
                            <button
                              onClick={() => saveTags(item.identifier)}
                              className="rounded-lg bg-emerald-500 px-3 py-1 text-xs font-semibold text-slate-900"
                            >
                              Save
                            </button>
                          </div>
                        ) : item.tags?.length ? (
                          <div className="flex flex-wrap gap-2 text-xs text-emerald-200">
                            {item.tags.map((tag) => (
                              <span key={tag} className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-1">
                                {tag}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex items-center gap-2">
                          <button
                            onClick={() =>
                              isEditing ? setEditingId(null) : startTagEdit(item.identifier, item.tags)
                            }
                            className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 transition hover:border-emerald-400/60 hover:text-emerald-200"
                          >
                            {isEditing ? 'Cancel' : 'Edit Tags'}
                          </button>
                          <button
                            onClick={() => handleDelete(item.identifier)}
                            className="rounded-md border border-red-500/50 px-2 py-1 text-xs text-red-300 transition hover:border-red-400 hover:text-red-200"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
