import { useEffect, useState } from "react";
import { data, Link, useNavigate, useParams } from "react-router-dom"

const ProductDetail = ({token, onCartChange, onAuthFail}) => {
    const {sku} = useParams();
    const navigate = useNavigate();
    const [product, setProduct] = useState(null);
    const [status, setStatus] = useState("");


    useEffect(() => {
        fetch(`http://localhost:3000/api/products/${sku}`)
        .then((res) => res.json())
        .then((data) => setProduct(data));
    },[sku])

    const handleAddToCart = async () => {
        if (!token) {
            setStatus("Please log in to add items to your cart.");
            return;
        }
        try {
            const res = await fetch(`http://localhost:3000/api/cart/${sku}?quantity=1`, {
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

    if(!product) return <p>Loading...</p>

    return (
        <div className="p-2 flex flex-col items-center">
            <Link to="/products">← Back to Products</Link>
            <h2 className="font-bold">{product.title}</h2>
            <p dangerouslySetInnerHTML={{__html : product.description}}/>
            <p>Price: ₹{product.price}</p>
            <p className={`text-sm ${
                  product.availability ? "text-green-600" : "text-red-600"
                }`}>{product.availability ? "In Stock" : "Out of Stock"}</p>
            <p>Category : {product.category}</p>
            {product.imagePath && (
                <img
                src={`http://localhost:8080${product.imagePath}`}
                alt={product.title}
                className="w-small h-40 w-60 object-cover rounded"/>
            )}
            {product.availability ? 
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
