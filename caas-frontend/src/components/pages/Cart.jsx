import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

const Cart = ({ token, onCartChange, onAuthFail }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const fetchCart = async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch("http://localhost:3000/api/cart", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 401) {
          if (onAuthFail) onAuthFail();
          navigate("/login");
          return;
        }
        throw new Error("Failed to load cart");
      }
      const data = await res.json();
      setItems(data);
      onCartChange(data.reduce((sum, i) => sum + (i.quantity || 0), 0));
    } catch (err) {
      setError(err.message);
      setItems([]);
      onCartChange(0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCart();
  }, [token]);

  const updateQuantity = async (sku, action) => {
    try {
      const url = `http://localhost:3000/api/cart/${encodeURIComponent(
        sku
      )}/${action}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        if (res.status === 401) {
          if (onAuthFail) onAuthFail();
          navigate("/login");
          return;
        }
        throw new Error("Update failed");
      }
      await fetchCart();
    } catch (err) {
      setError(err.message);
    }
  };

  const removeItem = async (sku) => {
    try {
      const res = await fetch(
        `http://localhost:3000/api/cart/${encodeURIComponent(sku)}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!res.ok && res.status !== 204) {
        if (res.status === 401) {
          if (onAuthFail) onAuthFail();
          navigate("/login");
          return;
        }
        throw new Error("Remove failed");
      }
      await fetchCart();
    } catch (err) {
      setError(err.message);
    }
  };

  const total = useMemo(
    () =>
      items.reduce(
        (sum, item) => sum + (item.price || 0) * (item.quantity || 0),
        0
      ),
    [items]
  );

  const handleCheckout = () =>{
    navigate("/checkout")
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-10">
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="text-sm text-gray-500">Your bag</p>
          <h1 className="text-3xl font-bold">Shopping Cart</h1>
        </div>
        <Link
          to="/products"
          className="text-blue-600 hover:underline font-medium"
        >
          Continue shopping
        </Link>
      </div>

      {loading ? (
        <div className="text-gray-600">Loading cart...</div>
      ) : error ? (
        <div className="text-red-600">{error}</div>
      ) : items.length === 0 ? (
        <div className="bg-white border border-dashed border-gray-300 rounded-xl p-10 text-center">
          <p className="text-lg font-semibold text-gray-700">
            Your cart is empty.
          </p>
          <p className="text-gray-500 mt-2">
            Discover products and add them to your cart.
          </p>
          <Link
            to="/products"
            className="inline-block mt-4 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          >
            Browse products
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-4">
            {items.map((item) => (
              <div
                key={item.sku}
                className="flex gap-4 bg-white border border-gray-200 rounded-xl shadow-sm p-4"
              >
                <div className="w-24 h-24 bg-gray-100 rounded-lg overflow-hidden">
                  {item.imagePath ? (
                    <img
                      src={`http://localhost:8080${item.imagePath}`}
                      alt={item.title}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-400 text-sm">
                      No image
                    </div>
                  )}
                </div>
                <div className="flex-1 flex flex-col">
                  <div className="flex justify-between">
                    <div>
                      <h3 className="text-lg font-semibold">{item.title}</h3>
                      <p className="text-sm text-gray-500">SKU: {item.sku}</p>
                      <p
                        className={`text-xs mt-1 ${
                          item.availability ? "text-green-600" : "text-red-600"
                        }`}
                      >
                        {item.availability ? "In stock" : "Out of stock"}
                      </p>
                    </div>
                    <button
                      onClick={() => removeItem(item.sku)}
                      className="text-sm text-red-500 hover:text-red-800"
                    >
                      Remove
                    </button>
                  </div>

                  <div className="mt-auto flex items-center justify-between">
                    <div className="flex items-center space-x-3">
                      <button
                        className="w-8 h-8 rounded-full border border-gray-300 text-lg leading-none"
                        onClick={() => updateQuantity(item.sku, "decrement")}
                      >
                        -
                      </button>
                      <span className="w-10 text-center font-semibold">
                        {item.quantity}
                      </span>
                      <button
                        className="w-8 h-8 rounded-full border border-gray-300 text-lg leading-none"
                        onClick={() => updateQuantity(item.sku, "increment")}
                      >
                        +
                      </button>
                    </div>
                    <div className="text-lg font-semibold text-blue-700">
                      ₹{(item.price || 0).toFixed(2)}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <aside className="bg-white border border-gray-200 rounded-xl shadow-sm p-6 h-fit">
            <h2 className="text-xl font-semibold mb-4">Summary</h2>
            <div className="flex justify-between text-gray-700 mb-2">
              <span>Items</span>
              <span>{items.length}</span>
            </div>
            <div className="flex justify-between text-gray-700 mb-4">
              <span>Subtotal</span>
              <span className="font-semibold">₹{total.toFixed(2)}</span>
            </div>
            <button onClick={handleCheckout} className="w-full py-3 rounded-lg bg-blue-600 text-white font-semibold hover:bg-blue-700 transition">
              Proceed to checkout
            </button>
          </aside>
        </div>
      )}
    </div>
  );
};

export default Cart;
