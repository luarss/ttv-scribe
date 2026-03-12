import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';

interface Vod {
  vod_id: string;
  streamer: string;
  title: string | null;
  duration: number | null;
  recorded_at: string | null;
  status: string;
}

export default function Home() {
  const [vods, setVods] = useState<Vod[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchVods();
  }, []);

  const fetchVods = async () => {
    try {
      const res = await fetch('/api/vods');
      if (!res.ok) throw new Error('Failed to fetch transcripts');
      const data = await res.json();
      // Handle wrapper {vods: [...]} and map metadata -> transcript_metadata
      const allVods = (Array.isArray(data) ? data : data.vods || []).map((v: Record<string, unknown>) => ({
        ...v,
        transcript_metadata: v.metadata,
      }));
      setVods(allVods.filter((v: Vod) => v.status === 'completed'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load transcripts');
    } finally {
      setLoading(false);
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

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-3xl font-bold mb-8">Transcripts</h1>

      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : error ? (
        <p className="text-red-500">{error}</p>
      ) : vods.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <p>No transcripts available yet.</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Streamer
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Title
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Date
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Duration
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {vods.map((vod) => (
                <tr key={vod.vod_id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="text-purple-600 font-medium">@{vod.streamer}</span>
                  </td>
                  <td className="px-6 py-4">
                    <p className="text-gray-900 truncate max-w-xs" title={vod.title || ''}>
                      {vod.title || 'Untitled'}
                    </p>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-gray-500">
                    {formatDate(vod.recorded_at)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-gray-500">
                    {formatDuration(vod.duration)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right">
                    <Link
                      to={`/transcript/${vod.vod_id}`}
                      className="text-purple-600 hover:text-purple-800 text-sm font-medium"
                    >
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
