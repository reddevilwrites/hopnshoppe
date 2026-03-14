import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { API_BASE } from "../../api";

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
      const res = await fetch(`${API_BASE}/cart`, {
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
      const url = `${API_BASE}/cart/${encodeURIComponent(
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
        `${API_BASE}/cart/${encodeURIComponent(sku)}`,
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

  const FREE_SHIPPING_THRESHOLD = 100;
  const shippingProgress = Math.min((total / FREE_SHIPPING_THRESHOLD) * 100, 100);
  const remainingForFreeShipping = Math.max(FREE_SHIPPING_THRESHOLD - total, 0);

  return (
    <div className="min-h-screen bg-[#f8f8f6]">
      <div className="max-w-6xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <p className="text-xs uppercase tracking-widest text-gray-400 font-semibold mb-1">Your Bag</p>
            <h1 className="text-4xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>Cart</h1>
          </div>
          <Link
            to="/products"
            className="text-sm text-gray-500 hover:text-black transition font-medium"
          >
            ← Continue shopping
          </Link>
        </div>

        {loading ? (
          <div className="text-gray-400 text-sm animate-pulse">Loading cart…</div>
        ) : error ? (
          <div className="text-red-500 text-sm">{error}</div>
        ) : items.length === 0 ? (
          <div className="bg-white rounded-3xl p-12 text-center shadow-sm">
            <p className="text-2xl font-bold mb-2" style={{ fontFamily: "'Playfair Display', serif" }}>
              Your cart is empty.
            </p>
            <p className="text-gray-400 text-sm mt-1 mb-6">
              Discover products and add them to your cart.
            </p>
            <Link
              to="/products"
              className="inline-block px-6 py-3 rounded-2xl bg-black text-[#dfff00] font-bold hover:bg-gray-900 transition"
            >
              Browse products
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Cart items */}
            <div className="lg:col-span-2 space-y-4">
              {items.map((item) => {
                // Normalise field names: CartItemDTO uses title/imagePath (AEM);
                // future unified enrichment may use name/imageUrl (MARKETPLACE)
                const displayName = item.title || item.name || item.sku;
                const displayImage = item.imagePath || item.imageUrl;
                const hasAvailability = item.availability !== null && item.availability !== undefined;

                return (
                  <div
                    key={item.sku}
                    className="flex gap-4 bg-white rounded-3xl shadow-sm p-4"
                  >
                    <div className="w-24 h-24 bg-gray-100 rounded-2xl overflow-hidden shrink-0">
                      {displayImage ? (
                        <img
                          src={displayImage}
                          alt={displayName}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-300 text-xs">
                          No image
                        </div>
                      )}
                    </div>
                    <div className="flex-1 flex flex-col">
                      <div className="flex justify-between">
                        <div>
                          <h3 className="text-base font-semibold leading-tight">{displayName}</h3>
                          <p className="text-xs text-gray-400 mt-0.5">SKU: {item.sku}</p>
                          {hasAvailability && (
                            <p className={`text-xs mt-1 ${item.availability ? "text-green-600" : "text-red-500"}`}>
                              {item.availability ? "In stock" : "Out of stock"}
                            </p>
                          )}
                        </div>
                        <button
                          onClick={() => removeItem(item.sku)}
                          className="text-xs text-gray-400 hover:text-red-500 transition"
                        >
                          Remove
                        </button>
                      </div>

                      <div className="mt-auto flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <button
                            className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 text-base font-bold transition flex items-center justify-center"
                            onClick={() => updateQuantity(item.sku, "decrement")}
                          >
                            −
                          </button>
                          <span className="w-8 text-center font-semibold text-sm">
                            {item.quantity}
                          </span>
                          <button
                            className="w-8 h-8 rounded-full bg-gray-100 hover:bg-gray-200 text-base font-bold transition flex items-center justify-center"
                            onClick={() => updateQuantity(item.sku, "increment")}
                          >
                            +
                          </button>
                        </div>
                        <div className="text-base font-bold">
                          ${(item.price || 0).toFixed(2)}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Summary — dark drawer panel */}
            <aside className="bg-gray-950 text-white rounded-3xl p-6 h-fit space-y-5">
              {/* Free Shipping progress */}
              <div>
                <div className="flex justify-between text-xs mb-2">
                  <span className="text-white/60">
                    {shippingProgress >= 100
                      ? "🎉 You've unlocked Free Shipping!"
                      : `$${remainingForFreeShipping.toFixed(2)} away from FREE Shipping`}
                  </span>
                </div>
                <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[#dfff00] rounded-full transition-all duration-500"
                    style={{ width: `${shippingProgress}%` }}
                  />
                </div>
              </div>

              {/* Totals */}
              <div className="space-y-2 border-t border-white/10 pt-4">
                <div className="flex justify-between text-white/60 text-sm">
                  <span>Items</span>
                  <span>{items.length}</span>
                </div>
                <div className="flex justify-between text-white text-base font-semibold">
                  <span>Subtotal</span>
                  <span>${total.toFixed(2)}</span>
                </div>
              </div>

              {/* Express checkout */}
              <div className="space-y-2.5">
                <p className="text-xs text-center text-white/40 uppercase tracking-wider">Express Checkout</p>
                <button className="w-full py-3.5 rounded-2xl bg-white text-black font-bold text-sm flex items-center justify-center gap-2 hover:bg-gray-100 transition">
                  <span className="text-base"></span> Apple Pay
                </button>
                <button className="w-full py-3.5 rounded-2xl bg-[#4285F4] text-white font-bold text-sm flex items-center justify-center gap-2 hover:opacity-90 transition">
                  <span className="font-black">G</span> Google Pay
                </button>
                <button className="w-full py-3.5 rounded-2xl bg-[#5A31F4] text-white font-bold text-sm flex items-center justify-center gap-2 hover:opacity-90 transition">
                  Shop Pay
                </button>
              </div>

              {/* Standard checkout */}
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-px bg-white/10" />
                  <span className="text-white/30 text-xs">or</span>
                  <div className="flex-1 h-px bg-white/10" />
                </div>
                <button
                  onClick={handleCheckout}
                  className="w-full py-3 rounded-2xl border border-white/20 text-white/70 text-sm font-medium hover:border-white/40 hover:text-white transition"
                >
                  Standard Checkout
                </button>
              </div>
            </aside>
          </div>
        )}
      </div>
    </div>
  );
};

export default Cart;
