import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import Home from './pages/Home';
import Search from './pages/Search';
import Transcript from './pages/Transcript';

function Navigation() {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <nav className="bg-white shadow-sm border-b">
      <div className="max-w-4xl mx-auto px-6">
        <div className="flex gap-8">
          <Link
            to="/"
            className={`py-4 border-b-2 font-medium transition-colors ${
              isActive('/')
                ? 'border-purple-600 text-purple-600'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            Home
          </Link>
          <Link
            to="/search"
            className={`py-4 border-b-2 font-medium transition-colors ${
              isActive('/search')
                ? 'border-purple-600 text-purple-600'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            Search
          </Link>
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <Navigation />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route path="/transcript/:vodId" element={<Transcript />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;