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

  const SkeletonCard = () => (
    <div className="border rounded-lg p-4 shadow h-full space-y-3">
      <div className="skeleton h-5 w-3/4" />
      <div className="skeleton h-3 w-full" />
      <div className="skeleton h-3 w-5/6" />
      <div className="skeleton h-4 w-1/4 mt-1" />
      <div className="skeleton h-3 w-1/3" />
      <div className="skeleton h-40 w-full mt-2" />
    </div>
  );

  return (
    <div className="p-6">
      <h1 className="text-3xl font-bold mb-4">Products</h1>

      <input
        type="text"
        placeholder="Search by title"
        className="border p-2 rounded mb-4 w-full max-w-md"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        {isLoading
          ? Array.from({ length: productsPerPage }).map((_, i) => (
              <div key={i} className="h-full">
                <SkeletonCard />
              </div>
            ))
          : paginated.map((p) => (
          <div key={p.id} className="h-full">
            <Link to={`/products/${p.id}`} state={{ product: p }}>
              <div className="border rounded-lg p-4 shadow hover:shadow-lg transition h-full">
                <h2 className="font-semibold text-xl mb-2">{p.name}</h2>
                <p
                  className="text-gray-600 text-sm mb-2"
                  dangerouslySetInnerHTML={{ __html: p.description }}
                />
                <p className="font-bold text-lg text-blue-700 mb-1">${p.price}</p>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  p.source === "MARKETPLACE"
                    ? "bg-purple-100 text-purple-700"
                    : "bg-green-100 text-green-700"
                }`}>
                  {p.source === "MARKETPLACE" ? "Marketplace" : "AEM Store"}
                </span>
                {p.imageUrl && (
                  <img
                  loading="lazy"
                  src={p.imageUrl}
                  alt={p.name}
                  className="w-full h-40 object-cover rounded mt-2"
                  />
                )}
              </div>
            </Link>
            </div>
          ))}
      </div>

      {/* Pagination */}
      <div className="flex justify-center gap-2 mt-6">
        {[...Array(totalPages)].map((_, i) => (
          <button
            key={i}
            onClick={() => setCurrentPage(i + 1)}
            className={`px-4 py-2 rounded ${
              currentPage === i + 1
                ? "bg-blue-600 text-white"
                : "bg-gray-200 hover:bg-gray-300"
            }`}
          >
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
};

export default ProductList;
