import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';

interface Transcript {
  id: number;
  vod_id: number;
  text: string;
  transcript_metadata: {
    segments_count: number;
    key_moments: Array<{ time: number; text: string }>;
  } | null;
  cost: number | null;
  created_at: string;
}

const API_BASE = 'http://localhost:8000';

export default function TranscriptPage() {
  const { vodId } = useParams<{ vodId: string }>();
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!vodId) return;

    fetch(`${API_BASE}/api/vods/${vodId}/transcript`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(res.status === 404 ? 'Transcript not found' : 'Failed to fetch');
        }
        return res.json();
      })
      .then(setTranscript)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [vodId]);

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <p className="text-gray-500">Loading transcript...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
          <Link to="/" className="text-purple-600 hover:text-purple-800 text-sm mt-2 inline-block">
            ← Back to Home
          </Link>
        </div>
      </div>
    );
  }

  if (!transcript) return null;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <Link to="/" className="text-purple-600 hover:text-purple-800 text-sm mb-4 inline-block">
        ← Back to Home
      </Link>

      <h1 className="text-2xl font-bold mb-4">Transcript</h1>

      {/* Metadata */}
      <div className="bg-white rounded-lg shadow-md p-6 mb-6">
        <div className="flex gap-6 text-sm text-gray-600">
          {transcript.cost !== null && (
            <div>
              <span className="font-medium">Cost:</span> ${transcript.cost.toFixed(4)}
            </div>
          )}
          {transcript.transcript_metadata?.segments_count && (
            <div>
              <span className="font-medium">Segments:</span> {transcript.transcript_metadata.segments_count}
            </div>
          )}
          <div>
            <span className="font-medium">Created:</span>{' '}
            {new Date(transcript.created_at).toLocaleString()}
          </div>
        </div>

        {/* Key Moments */}
        {transcript.transcript_metadata?.key_moments && transcript.transcript_metadata.key_moments.length > 0 && (
          <div className="mt-4 pt-4 border-t">
            <h3 className="font-medium mb-2">Key Moments</h3>
            <div className="space-y-2">
              {transcript.transcript_metadata.key_moments.map((moment, idx) => (
                <div key={idx} className="flex gap-3 text-sm">
                  <span className="text-purple-600 font-mono min-w-[50px]">
                    {formatTime(moment.time)}
                  </span>
                  <span className="text-gray-700">{moment.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Full Transcript */}
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-lg font-semibold mb-4">Full Transcript</h2>
        <div className="prose max-w-none">
          {transcript.text.split('\n').map((paragraph, idx) => (
            <p key={idx} className="mb-4 text-gray-700 leading-relaxed">
              {paragraph}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}