import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FiMenu, FiX, FiShoppingCart, FiUser, FiSearch } from "react-icons/fi";
import { useNavigate, useLocation } from "react-router-dom";
import { API_BASE } from "../api";

export default function Header({ token, onLogout, cartCount = 0, userName = "" }) {
  const [mobileOpen, setMobileOpen]       = useState(false);
  const [dropDown, setDropDown]           = useState(false);
  const [searchQuery, setSearchQuery]     = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError]     = useState(false);
  const [searchOpen, setSearchOpen]       = useState(false);

  const userMenuRef   = useRef();
  const searchRef     = useRef();
  const debounceTimer = useRef(null);
  const abortCtrl     = useRef(null);

  const navigate     = useNavigate();
  const { pathname } = useLocation();

  // Close user dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setDropDown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Close search dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ---------------------------------------------------------------------------
  // Debounced search with AbortController for stale-request cancellation
  // ---------------------------------------------------------------------------
  const doSearch = useCallback((q) => {
    // Cancel any in-flight request before issuing a new one
    if (abortCtrl.current) abortCtrl.current.abort();
    abortCtrl.current = new AbortController();

    setSearchLoading(true);
    setSearchError(false);

    fetch(`${API_BASE}/search?q=${encodeURIComponent(q)}&limit=8`, {
      signal: abortCtrl.current.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setSearchResults(data.results || []);
        setSearchLoading(false);
      })
      .catch((err) => {
        if (err.name === "AbortError") return; // stale request — safe to ignore
        setSearchError(true);
        setSearchLoading(false);
      });
  }, []);

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchQuery(value);
    clearTimeout(debounceTimer.current);

    if (!value.trim()) {
      if (abortCtrl.current) abortCtrl.current.abort();
      setSearchResults([]);
      setSearchOpen(false);
      setSearchLoading(false);
      return;
    }

    setSearchOpen(true);
    // 300 ms debounce — only fires when the user pauses typing
    debounceTimer.current = setTimeout(() => doSearch(value.trim()), 300);
  };

  const handleResultClick = () => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchResults([]);
  };

  const links = [
    { name: "Home",     href: "/" },
    { name: "Products", href: "/products" },
    { name: "About",    href: "/about" },
    { name: "Contact",  href: "/contact" },
  ];

  return (
    <header className="sticky top-0 z-50 backdrop-blur bg-white/50 shadow-sm">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-6">
        {/* Logo */}
        <a href="/" className="text-2xl font-bold text-yellow-400 shrink-0">
          HopNShoppe
        </a>

        {/* Desktop nav */}
        <nav className="hidden md:flex space-x-8 shrink-0">
          {links.map((l) => (
            <a
              key={l.name}
              href={l.href}
              className="relative text-gray-700 hover:text-blue-600 transition"
            >
              {l.name}
            </a>
          ))}
        </nav>

        {/* Search bar — desktop only */}
        <div className="relative hidden md:block flex-1 max-w-xs" ref={searchRef}>
          <div className="relative">
            <FiSearch
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
              size={14}
            />
            <input
              type="text"
              placeholder="Search products…"
              className="w-full border border-gray-200 rounded-full pl-8 pr-4 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300 bg-white/80"
              value={searchQuery}
              onChange={handleSearchChange}
              onFocus={() => searchQuery.trim() && setSearchOpen(true)}
            />
          </div>

          {/* Inline search results dropdown */}
          {searchOpen && (
            <div className="absolute top-full left-0 mt-1 w-80 bg-white rounded-lg shadow-xl border border-gray-100 z-50 overflow-hidden">
              {/* Loading state */}
              {searchLoading && (
                <div className="p-4 text-center text-sm text-gray-500">Searching…</div>
              )}

              {/* Error state */}
              {!searchLoading && searchError && (
                <div className="p-4 text-center text-sm text-red-500">
                  Search unavailable — try again shortly
                </div>
              )}

              {/* Empty state */}
              {!searchLoading && !searchError && searchResults.length === 0 && (
                <div className="p-4 text-center text-sm text-gray-500">
                  No results for &ldquo;{searchQuery}&rdquo;
                </div>
              )}

              {/* Results — price comes from denormalized_doc, no follow-up fetch */}
              {!searchLoading && !searchError && searchResults.map((result) => (
                <Link
                  key={result.id}
                  to={result.slug}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition border-b border-gray-50 last:border-0"
                  onClick={handleResultClick}
                >
                  {result.image?.url ? (
                    <img
                      src={result.image.url}
                      alt={result.title}
                      className="w-10 h-10 object-cover rounded shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 bg-gray-100 rounded shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">
                      {result.title}
                    </div>
                    <div className="text-xs text-blue-600 font-semibold">
                      {result.price?.formatted}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Right-side actions */}
        <div className="flex items-center space-x-4 ml-auto">
          {pathname !== "/cart" && (
            <a href="/cart" className="relative text-gray-700 hover:text-blue-600 transition">
              <FiShoppingCart size={20} />
              {cartCount > 0 && (
                <span className="absolute -top-2 -right-3 bg-red-500 text-white text-xs rounded-full px-2 py-0.5">
                  {cartCount}
                </span>
              )}
            </a>
          )}
          {token ? (
            <button
              onClick={() => setDropDown((open) => !open)}
              className="flex items-center space-x-2 text-gray-700 hover:text-blue-600"
            >
              <FiUser size={20} />
              <span className="hidden md:inline">Hi{userName ? `, ${userName}` : ""}</span>
            </button>
          ) : (
            <a href="/login" className="text-gray-700 hover:text-blue-600 transition">
              <FiUser size={20} />
            </a>
          )}

          {/* User account dropdown */}
          {dropDown && (
            <div
              ref={userMenuRef}
              className="absolute right-0 mt-2 w-48 bg-white border border-gray-200 rounded-md shadow-lg z-50"
            >
              <button
                onClick={() => { navigate("/account"); setDropDown(false); }}
                className="w-full text-left px-4 py-2 hover:bg-gray-100"
              >
                Profile
              </button>
              <button
                onClick={() => { onLogout(); setDropDown(false); navigate("/login"); }}
                className="w-full text-left px-4 py-2 hover:bg-gray-100"
              >
                Logout
              </button>
            </div>
          )}

          {/* Mobile menu button */}
          <button
            className="md:hidden text-gray-700 hover:text-blue-600"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            {mobileOpen ? <FiX size={24} /> : <FiMenu size={24} />}
          </button>
        </div>
      </div>

      {/* Mobile nav panel */}
      {mobileOpen && (
        <nav className="md:hidden bg-white border-t border-gray-200">
          <ul className="flex flex-col px-6 py-4 space-y-3">
            {links.map((l) => (
              <li key={l.name}>
                <a
                  href={l.href}
                  className="block text-gray-700 hover:text-blue-600 transition"
                >
                  {l.name}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
