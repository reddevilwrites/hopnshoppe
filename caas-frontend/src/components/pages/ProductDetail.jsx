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

    if (!product) return <p>Loading...</p>;

    // Normalise field names: UnifiedProductDTO uses name/imageUrl; AEM ProductDTO uses title/imagePath
    const displayName = product.name || product.title;
    const displayImage = product.imageUrl || product.imagePath;
    const isMarketplace = product.source === "MARKETPLACE";
    // AEM products have explicit availability; marketplace products are treated as available
    const isAvailable = product.availability !== undefined ? product.availability : true;

    return (
        <div className="p-2 flex flex-col items-center">
            <Link to="/products">← Back to Products</Link>
            <h2 className="font-bold">{displayName}</h2>
            {product.source && (
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium mb-1 ${
                    isMarketplace ? "bg-purple-100 text-purple-700" : "bg-green-100 text-green-700"
                }`}>
                    {isMarketplace ? "Marketplace" : "AEM Store"}
                </span>
            )}
            <p dangerouslySetInnerHTML={{__html : product.description}}/>
            <p>Price: ${product.price}</p>
            {product.availability !== undefined && (
                <p className={`text-sm ${isAvailable ? "text-green-600" : "text-red-600"}`}>
                    {isAvailable ? "In Stock" : "Out of Stock"}
                </p>
            )}
            {product.category && <p>Category : {product.category}</p>}
            {displayImage && (
                <img
                src={displayImage}
                alt={displayName}
                className="w-small h-40 w-60 object-cover rounded"/>
            )}
            {isAvailable ?
            <button
                onClick={handleAddToCart}
                className="mt-4 px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700"
            >
                Add to Cart
            </button>
            :
            <button
                className="mt-4 px-4 py-2 rounded bg-amber-600 text-white hover:bg-amber-700"
            >
                Notify Me
            </button>
            }

            {status && <p className="mt-2 text-sm text-gray-700">{status}</p>}
        </div>
    )
}
export default ProductDetail;
