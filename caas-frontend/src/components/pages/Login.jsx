import axios from "axios";
import { useState } from "react"
import ShopperImage from "../../assets/images/shopper.jpg"
import { Navigate } from "react-router-dom";
import { API_ROOT } from "../../api";

const Login = ({onLogin}) => {

    const[username, setUsername] = useState('');
    const[password, setPassword] = useState('');
    const[error, setError] = useState('');
    const [isLoggedIn, setIsLoggedIn] = useState(false);

    const handleLogin = async (e) => {
        e.preventDefault();
        try {
            const response = await axios.post(`${API_ROOT || ''}/auth/login`,{
                username,
                password
            });
            const token = response.data.token;
            sessionStorage.setItem("token", token);
            onLogin(token);
            setIsLoggedIn(true)

        } catch (error) {
            setError("Invalid Credentials")
        }
    }

    return(
        <>
        {!isLoggedIn ? (
            <div className="min-h-screen flex">
            <div className="hidden md:flex w-1/2 bg-yellow-200 items-center justify-center">
                <img 
                src={ShopperImage}
                alt="Happy Shopper"
                className="object-cover h-full w-full rounded-l-xl"
                />
            </div>

            <div className="flex flex-col w-full md:w-1/2 bg-amber-300 items-center justify-center">
                <form onSubmit={handleLogin} className="bg-white p-8 rounded-xl shadow-md w-full max-w-sm">
                    <h2 className="text-2xl font-bold text-center mb-6 text-black">Welcome to HopNShoppe</h2>
                    <div className="mb-4">
                        <label className="block text-sm font-medium mb-1 text-gray-700 text-left">
                            Username
                        </label>
                        <input type="text" className="w-full px-4 py-2 bg-gray-300 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required/>
                    </div>
                    <div className="mb-6">
                        <label className="block text-sm font-medium mb-1 text-gray-700 text-left">
                            Password
                        </label>
                        <input className="w-full px-4 py-2 bg-gray-300 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="Password" value={password} type="password" onChange={(e) => setPassword(e.target.value)} required/>
                    </div>
                    {error && <div className="text-red-700 mb-4 text-sm">{error}</div>}
                    <button className="w-20 font-bold bg-yellow-300 mt-4 text-black py-2 rounded-md hover:bg-yellow-700 transition duration-200" type="submit">Login</button>
                    <p className="mt-4 text-center text-sm text-gray-600">
                        Don’t have an account?{" "}
                        <a href="/signup" className="text-blue-600 hover:underline">
                        Sign up
                        </a>
                    </p>
                
                </form>
        </div>

        </div>
        ):  (
            <Navigate to="/products"/>
        )}
        
        </>
        
    )
}

export default Login;
