import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../../api";

const ProductList = ({token}) => {
  const [allProducts, setAllProducts] = useState([]);
  const [visibleProducts, setVisibleProducts] = useState([]);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  const productsPerPage = 6;

  useEffect(() => {
    fetch(`${API_BASE}/products/unified`)
      .then((res) => res.json())
      .then((data) => {
        setAllProducts(data);
        setVisibleProducts(data);
      });
  }, []);

  useEffect(() => {
    const filtered = allProducts.filter((p) =>
      p.name.toLowerCase().includes(search.toLowerCase())
    );
    setVisibleProducts(filtered);
    setCurrentPage(1);
  }, [search, allProducts]);

  const paginated = visibleProducts.slice(
    (currentPage - 1) * productsPerPage,
    currentPage * productsPerPage
  );

  const totalPages = Math.ceil(visibleProducts.length / productsPerPage);

  const isLoading = allProducts.length === 0 && search === "";

  const SkeletonCard = ({ featured = false }) => (
    <div className={`bg-white rounded-3xl p-5 shadow-md space-y-3 ${featured ? "col-span-2" : ""}`}>
      <div className="skeleton h-5 w-3/4" />
      <div className="skeleton h-3 w-full" />
      <div className="skeleton h-3 w-5/6" />
      <div className="skeleton h-4 w-1/4 mt-1" />
      <div className={`skeleton w-full mt-2 rounded-2xl ${featured ? "h-64" : "h-40"}`} />
    </div>
  );

  const tiktokItems = [
    { id: 1, label: "Cyberpunk\nAudiophile\nDrops" },
    { id: 2, label: "Speaker-007\nUnboxing" },
    { id: 3, label: "Chair-004\nSetup Tour" },
    { id: 4, label: "Keyboard\nRGB Setup" },
  ];

  return (
    <div className="min-h-screen bg-[#f8f8f6]">
      <div className="max-w-7xl mx-auto px-6 pt-8 pb-4">
        {/* Page header */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
          <div>
            <p className="text-xs uppercase tracking-widest text-gray-400 mb-1 font-semibold">All Products</p>
            <h1 className="text-5xl font-bold leading-tight" style={{ fontFamily: "'Playfair Display', serif" }}>Shop</h1>
          </div>
          <input
            type="text"
            placeholder="Filter by title…"
            className="border border-gray-200 bg-white px-4 py-2.5 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-[#dfff00]/60 w-full sm:w-64"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Editorial asymmetric grid — 3 columns; first card per page is featured (col-span-2) */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-5">
          {isLoading
            ? Array.from({ length: productsPerPage }).map((_, i) => (
                <SkeletonCard key={i} featured={i === 0} />
              ))
            : paginated.map((p, localIndex) => {
                const featured = localIndex === 0;
                const isMarketplace = p.source === "MARKETPLACE";
                return (
                  <div key={p.id} className={`group ${featured ? "col-span-2" : ""}`}>
                    <Link to={`/products/${p.id}`} state={{ product: p }}>
                      <div className="relative bg-white rounded-3xl p-5 shadow-md hover:shadow-xl transition-all duration-300 h-full overflow-hidden">
                        <h2
                          className="font-semibold text-lg mb-1 leading-tight"
                          style={{ fontFamily: "'Playfair Display', serif" }}
                        >
                          {p.name}
                        </h2>
                        <p
                          className="text-gray-500 text-xs mb-3 line-clamp-2"
                          dangerouslySetInnerHTML={{ __html: p.description }}
                        />
                        <p className="font-bold text-xl mb-2">${p.price}</p>
                        <span className={`inline-block text-xs px-3 py-0.5 rounded-full font-semibold mb-3 ${
                          isMarketplace
                            ? "bg-purple-100 text-purple-700"
                            : "bg-[#dfff00]/40 text-black glow-lime"
                        }`}>
                          {isMarketplace ? "Marketplace" : "AEM Store"}
                        </span>
                        {p.imageUrl && (
                          <img
                            loading="lazy"
                            src={p.imageUrl}
                            alt={p.name}
                            className={`w-full object-cover rounded-2xl ${featured ? "h-64" : "h-40"}`}
                          />
                        )}
                        {/* Quick Add — appears on card hover */}
                        <div className="absolute bottom-5 left-5 right-5 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
                          <div className="bg-black text-[#dfff00] text-xs font-bold text-center py-2.5 rounded-full">
                            Quick Add +
                          </div>
                        </div>
                      </div>
                    </Link>
                  </div>
                );
              })}
        </div>

        {/* Pagination */}
        <div className="flex justify-center gap-2 mt-8 mb-4">
          {[...Array(totalPages)].map((_, i) => (
            <button
              key={i}
              onClick={() => setCurrentPage(i + 1)}
              className={`w-10 h-10 rounded-full text-sm font-semibold transition ${
                currentPage === i + 1
                  ? "bg-black text-[#dfff00]"
                  : "bg-white text-gray-600 hover:bg-gray-100 shadow-sm"
              }`}
            >
              {i + 1}
            </button>
          ))}
        </div>
      </div>

      {/* Seen on TikTok */}
      <div className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex items-center gap-3 mb-6">
          <span className="text-xl">▶</span>
          <h2 className="text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
            Seen on TikTok
          </h2>
          <span className="ml-2 text-xs uppercase tracking-widest text-gray-400 font-semibold">· trending</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {tiktokItems.map((item) => (
            <div
              key={item.id}
              className="relative rounded-3xl overflow-hidden bg-gradient-to-br from-gray-900 to-gray-700 cursor-pointer group"
              style={{ aspectRatio: "9/16" }}
            >
              <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
              <div className="absolute inset-0 flex flex-col items-center justify-end p-4">
                <div className="mb-3 w-10 h-10 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center group-hover:bg-[#dfff00] transition-all duration-300">
                  <span className="text-white group-hover:text-black text-sm pl-0.5">▶</span>
                </div>
                <p className="text-white text-xs font-semibold text-center leading-tight whitespace-pre-line">
                  {item.label}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ProductList;
