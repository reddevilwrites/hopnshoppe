import { useEffect, useRef, useState } from "react";
import { FiMenu, FiX, FiShoppingCart, FiUser } from "react-icons/fi"; // lucide-react works similarly
import { useNavigate } from "react-router-dom";

export default function Header({ token, onLogout }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [dropDown, setDropDown] = useState(false);
  const ref = useRef();
  const navigate = useNavigate();


  useEffect(() => {
    const handler = (event) => {
        if(ref.current && !ref.current.contains(event.target)){
            setDropDown(false)
        }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler)
  },[]);

  const links = [
    { name: "Home", href: "/" },
    { name: "Products", href: "/products" },
    { name: "About", href: "/about" },
    { name: "Contact", href: "/contact" },
  ];

  return (
    <header className="sticky top-0 z-50 backdrop-blur bg-white/50 shadow-sm">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        {/* Logo */}
        <a href="/" className="text-2xl font-bold text-yellow-400">
          HopNShoppe
        </a>

        {/* Desktop nav */}
        <nav className="hidden md:flex space-x-8">
          {links.map((l) => (
            <a
              key={l.name}
              href={l.href}
              className="relative text-gray-700 hover:text-blue-600 transition"
            >
              {l.name}
              <span className="absolute left-0 -bottom-1 w-0 h-0.5 bg-blue-600 group-hover:w-full transition-all"></span>
            </a>
          ))}
        </nav>

        {/* Right-side actions */}
        <div className="flex items-center space-x-4">
          <a href="/cart" className="text-gray-700 hover:text-blue-600 transition">
            <FiShoppingCart size={20} />
          </a>
          {token ? (
            <button
              onClick={() => setDropDown((open) => (!open))}
              className="flex items-center space-x-2 text-gray-700 hover:text-blue-600"
            >
              <FiUser size={20}/>
              <span className="hidden md:inline">Account</span>
            </button>
          ) : (
            <a href="/login" className="text-gray-700 hover:text-blue-600 transition">
              <FiUser size={20} />
            </a>
          )}

          {/* Dropdown */}
          {dropDown && 
          (
            <div ref={ref}
            className="absolute  right-0 mt-2 w-48 bg-white border border-gray-200 rounded-md shadow-lg z-50"
            >
                <button 
                onClick={() => {
                    navigate('/account');
                    setDropDown(false)
                }}
                className="w-full text-left px-4 py-2 hover:bg-gray-100"
                >
                    Profile
                </button>
                <button 
                onClick={() => {
                    onLogout();
                    setDropDown(false);
                    navigate('/login');
                }}
                className="w-full text-left px-4 py-2 hover:bg-gray-100">
                    Logout
                </button>
            </div>
          )}
          {/* Mobile menu button */}
          <button
            className="md:hidden text-gray-700 hover:text-blue-600"
            onClick={() => setMobileOpen(!mobileOpen)}
          >
            {mobileOpen ? <FiX size={24}/> : <FiMenu size={24}/>}
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
