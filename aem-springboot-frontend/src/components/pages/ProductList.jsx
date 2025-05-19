import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const ProductList = ({token}) => {
  const [allProducts, setAllProducts] = useState([]);
  const [visibleProducts, setVisibleProducts] = useState([]);
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);

  const productsPerPage = 6;

  useEffect(() => {
    fetch("http://localhost:3000/api/products")
      .then((res) => res.json())
      .then((data) => {
        setAllProducts(data);
        setVisibleProducts(data);
      });
  }, []);

  useEffect(() => {
    const filtered = allProducts.filter((p) =>
      p.title.toLowerCase().includes(search.toLowerCase())
    );
    setVisibleProducts(filtered);
    setCurrentPage(1); // reset to page 1 on new search
  }, [search, allProducts]);

  const paginated = visibleProducts.slice(
    (currentPage - 1) * productsPerPage,
    currentPage * productsPerPage
  );

  const totalPages = Math.ceil(visibleProducts.length / productsPerPage);

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
        {paginated.map((p) => (
        <div key={p.sku} className="h-full">
          <Link to={`/products/${p.sku}`}>
            <div className="border rounded-lg p-4 shadow hover:shadow-lg transition h-full">
              <h2 className="font-semibold text-xl mb-2">{p.title}</h2>
              <p
                className="text-gray-600 text-sm mb-2"
                dangerouslySetInnerHTML={{ __html: p.description }}
              />
              <p className="font-bold text-lg text-blue-700 mb-1">₹{p.price}</p>
              <p
                className={`text-sm ${
                  p.availability ? "text-green-600" : "text-red-600"
                }`}
              >
                {p.availability ? "In Stock" : "Out of Stock"}
              </p>
              {p.imagePath && (
                <img
                loading="lazy"
                src={`http://localhost:8080${p.imagePath}`}
                alt={p.title}
                className="w-full h-40 object-cover rounded"
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
