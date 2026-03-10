import { useState, useEffect } from 'react';

interface Streamer {
  id: number;
  username: string;
  twitch_id: string | null;
  created_at: string;
}

interface Vod {
  id: number;
  vod_id: string;
  title: string | null;
  duration: number | null;
  recorded_at: string | null;
  status: string;
}

const API_BASE = 'http://localhost:8000';

export default function Home() {
  const [streamers, setStreamers] = useState<Streamer[]>([]);
  const [newStreamer, setNewStreamer] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStreamers();
  }, []);

  const fetchStreamers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/streamers`);
      const data = await res.json();
      setStreamers(data);
    } catch (err) {
      console.error('Failed to fetch streamers:', err);
    } finally {
      setLoading(false);
    }
  };

  const addStreamer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newStreamer.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/api/streamers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newStreamer }),
      });

      if (res.ok) {
        setNewStreamer('');
        fetchStreamers();
      }
    } catch (err) {
      console.error('Failed to add streamer:', err);
    }
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '-';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${s}s`;
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-3xl font-bold mb-8">TTV-Scribe</h1>

      {/* Add Streamer Form */}
      <form onSubmit={addStreamer} className="mb-8 flex gap-2">
        <input
          type="text"
          value={newStreamer}
          onChange={(e) => setNewStreamer(e.target.value)}
          placeholder="Enter Twitch username"
          className="flex-1 px-4 py-2 border rounded-lg focus:ring-2 focus:ring-purple-500 focus:outline-none"
        />
        <button
          type="submit"
          className="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors"
        >
          Add Streamer
        </button>
      </form>

      {/* Streamers List */}
      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : streamers.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p>No streamers tracked yet.</p>
          <p className="text-sm">Add a streamer above to get started.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {streamers.map((streamer) => (
            <StreamerCard key={streamer.id} streamer={streamer} formatDuration={formatDuration} />
          ))}
        </div>
      )}
    </div>
  );
}

function StreamerCard({ streamer, formatDuration }: { streamer: Streamer; formatDuration: (s: number | null) => string }) {
  const [vods, setVods] = useState<Vod[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/api/streamers/${streamer.id}/recent?limit=5`)
      .then((res) => res.json())
      .then(setVods)
      .catch(console.error);
  }, [streamer.id]);

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h2 className="text-xl font-semibold mb-4">@{streamer.username}</h2>
      {vods.length > 0 ? (
        <div className="space-y-2">
          {vods.map((vod) => (
            <div
              key={vod.id}
              className="flex items-center justify-between py-2 border-b last:border-0"
            >
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{vod.title || 'Untitled'}</p>
                <p className="text-sm text-gray-500">
                  {vod.recorded_at ? new Date(vod.recorded_at).toLocaleDateString() : ''}
                </p>
              </div>
              <div className="flex items-center gap-4 ml-4">
                <span className="text-sm text-gray-600">{formatDuration(vod.duration)}</span>
                <span
                  className={`px-2 py-1 text-xs rounded-full ${
                    vod.status === 'completed'
                      ? 'bg-green-100 text-green-800'
                      : vod.status === 'failed'
                      ? 'bg-red-100 text-red-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}
                >
                  {vod.status}
                </span>
                {vod.status === 'completed' && (
                  <a
                    href={`/transcript/${vod.vod_id}`}
                    className="text-purple-600 hover:text-purple-800 text-sm"
                  >
                    View Transcript
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500 text-sm">No VODs yet</p>
      )}
    </div>
  );
}