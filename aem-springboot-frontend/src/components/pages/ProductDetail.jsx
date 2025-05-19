import { useEffect, useState } from "react";
import { data, Link, useParams } from "react-router-dom"

const ProductDetail = ({token}) => {
    const {sku} = useParams();
    const [product, setProduct] = useState(null);


    useEffect(() => {
        fetch(`http://localhost:3000/api/products/${sku}`)
        .then((res) => res.json())
        .then((data) => setProduct(data));
    },[sku])

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
        </div>
    )
}
export default ProductDetail;