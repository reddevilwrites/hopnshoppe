import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { API_BASE } from "../../api";

const ProductDetail = ({token, onCartChange, onAuthFail}) => {
    const {sku} = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const passedProduct = location.state?.product;

    const [product, setProduct] = useState(null);
    const [status, setStatus] = useState("");

    useEffect(() => {
        if (passedProduct) {
            setProduct(passedProduct);
            return;
        }
        fetch(`${API_BASE}/products/unified/${sku}`)
        .then((res) => res.json())
        .then((data) => setProduct(data));
    }, [sku]);

    const handleAddToCart = async () => {
        if (!token) {
            setStatus("Please log in to add items to your cart.");
            return;
        }
        try {
            const res = await fetch(`${API_BASE}/cart/${sku}?quantity=1`, {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${token}`
                }
            });
            if (res.ok) {
                setStatus("Added to cart.");
                if (onCartChange) {
                    onCartChange();
                }
            } else if (res.status === 401) {
                setStatus("Session expired. Please log in again.");
                if (onAuthFail) {
                    onAuthFail();
                }
                navigate("/login");
            } else {
                setStatus("Could not add to cart. Please try again.");
            }
        } catch (err) {
            setStatus("Error adding to cart.");
        }
    }

    if (!product) return (
        <div className="min-h-screen bg-[#f8f8f6] flex items-center justify-center">
            <div className="text-gray-400 text-sm animate-pulse">Loading…</div>
        </div>
    );

    // Normalise field names: UnifiedProductDTO uses name/imageUrl; AEM ProductDTO uses title/imagePath
    const displayName = product.name || product.title;
    const displayImage = product.imageUrl || product.imagePath;
    const isMarketplace = product.source === "MARKETPLACE";
    // AEM products have explicit availability; marketplace products are treated as available
    const isAvailable = product.availability !== undefined ? product.availability : true;

    return (
        <div className="min-h-screen bg-[#f8f8f6]">
            <div className="max-w-6xl mx-auto px-6 py-8">
                <Link
                    to="/products"
                    className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-black transition mb-8"
                >
                    ← Back to Products
                </Link>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-start">
                    {/* Left: Image */}
                    <div>
                        {displayImage ? (
                            <img
                                src={displayImage}
                                alt={displayName}
                                className="w-full rounded-3xl object-cover aspect-square shadow-xl"
                            />
                        ) : (
                            <div className="w-full aspect-square bg-gray-100 rounded-3xl flex items-center justify-center text-gray-300 text-sm">
                                No image
                            </div>
                        )}
                    </div>

                    {/* Right: Product info — sticky on large screens */}
                    <div className="lg:sticky lg:top-28 space-y-5">
                        {/* Source badge */}
                        {product.source && (
                            <span className={`inline-block text-xs px-3 py-1 rounded-full font-semibold ${
                                isMarketplace
                                    ? "bg-purple-100 text-purple-700"
                                    : "bg-[#dfff00]/40 text-black glow-lime"
                            }`}>
                                {isMarketplace ? "Marketplace" : "AEM Store"}
                            </span>
                        )}

                        {/* Title */}
                        <h2
                            className="text-4xl font-bold leading-tight"
                            style={{ fontFamily: "'Playfair Display', serif" }}
                        >
                            {displayName}
                        </h2>

                        {/* Price */}
                        <p className="text-3xl font-bold">${product.price}</p>

                        {/* Availability */}
                        {product.availability !== undefined && (
                            <p className={`text-sm font-medium ${isAvailable ? "text-green-600" : "text-red-500"}`}>
                                {isAvailable ? "✓ In Stock" : "✗ Out of Stock"}
                            </p>
                        )}

                        {/* Category */}
                        {product.category && (
                            <p className="text-sm text-gray-500">
                                Category: <span className="text-gray-800 font-medium">{product.category}</span>
                            </p>
                        )}

                        {/* Description */}
                        <p
                            className="text-gray-600 text-sm leading-relaxed"
                            dangerouslySetInnerHTML={{ __html: product.description }}
                        />

                        {/* Sustainability Score widget */}
                        <div className="bg-white rounded-2xl p-4 flex items-center gap-4 shadow-sm border border-gray-100">
                            <span className="text-2xl">🌿</span>
                            <div>
                                <p className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Sustainability Score</p>
                                <div className="flex items-center gap-2 mt-1">
                                    <div className="flex gap-0.5">
                                        {[1, 2, 3, 4, 5].map((n) => (
                                            <div
                                                key={n}
                                                className={`w-5 h-1.5 rounded-full ${n <= 4 ? "bg-[#dfff00]" : "bg-gray-200"}`}
                                            />
                                        ))}
                                    </div>
                                    <span className="text-sm font-bold">4.8 / 5</span>
                                </div>
                            </div>
                        </div>

                        {/* Add to Cart / Notify Me */}
                        {isAvailable ? (
                            <button
                                onClick={handleAddToCart}
                                className="w-full py-4 rounded-2xl bg-black text-[#dfff00] font-bold text-base tracking-wide hover:bg-gray-900 transition-all duration-200"
                            >
                                Add to Cart
                            </button>
                        ) : (
                            <button
                                className="w-full py-4 rounded-2xl bg-gray-100 text-gray-800 font-bold text-base tracking-wide hover:bg-gray-200 transition-all duration-200"
                            >
                                Notify Me
                            </button>
                        )}

                        {status && (
                            <p className={`text-sm text-center ${status.includes("Added") ? "text-green-600" : "text-gray-500"}`}>
                                {status}
                            </p>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
export default ProductDetail;
