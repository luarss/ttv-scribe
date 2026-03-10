import { useState } from 'react';
import { Link } from 'react-router-dom';

interface SearchResult {
  transcript_id: number;
  vod_id: string;
  vod_title: string | null;
  streamer: string;
  recorded_at: string | null;
  text_preview: string;
  rank: number;
}

const API_BASE = 'http://localhost:8000';

export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || query.length < 2) return;

    setSearching(true);
    try {
      const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      setResults(data);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-3xl font-bold mb-8">Search Transcripts</h1>

      <form onSubmit={handleSearch} className="mb-8">
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for keywords in transcripts..."
            className="flex-1 px-4 py-3 border rounded-lg focus:ring-2 focus:ring-purple-500 focus:outline-none text-lg"
          />
          <button
            type="submit"
            disabled={searching || query.length < 2}
            className="px-8 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
      </form>

      {results.length > 0 ? (
        <div className="space-y-4">
          <p className="text-gray-500 mb-4">{results.length} results found</p>
          {results.map((result) => (
            <div
              key={result.transcript_id}
              className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow"
            >
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="text-lg font-semibold">{result.vod_title || 'Untitled'}</h3>
                  <p className="text-purple-600">@{result.streamer}</p>
                </div>
                <span className="text-sm text-gray-500">
                  {result.recorded_at ? new Date(result.recorded_at).toLocaleDateString() : ''}
                </span>
              </div>
              <p className="text-gray-700 mt-3">{result.text_preview}</p>
              <Link
                to={`/transcript/${result.vod_id}`}
                className="inline-block mt-3 text-purple-600 hover:text-purple-800 text-sm font-medium"
              >
                View Full Transcript →
              </Link>
            </div>
          ))}
        </div>
      ) : query.length >= 2 && !searching ? (
        <p className="text-gray-500 text-center py-12">No results found for "{query}"</p>
      ) : (
        <p className="text-gray-500 text-center py-12">
          Enter at least 2 characters to search transcripts
        </p>
      )}
    </div>
  );
}