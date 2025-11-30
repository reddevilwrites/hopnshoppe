import { lazy, Suspense, useEffect, useState } from 'react'
import { Buffer } from 'buffer'
import './App.css'
import Header from './components/Header'
import { Navigate, Route, Routes } from 'react-router-dom'
import Home from './components/pages/Home'
import Signup from './components/pages/Signup'
import Account from './components/pages/Account'
import Checkout from './components/pages/Checkout'

function App() {
  const [count, setCount] = useState(0)
  const [token, setToken] = useState(sessionStorage.getItem('token'));
  const [userName, setUserName] = useState(sessionStorage.getItem('username') || "");

  const ProductList = lazy(() => import('./components/pages/ProductList'));

  const ProductDetail = lazy(() => import('./components/pages/ProductDetail'));

  const Login = lazy(() => import('./components/pages/Login'));
  const Cart = lazy(() => import('./components/pages/Cart'));

  const [cartCount, setCartCount] = useState(0);

  const refreshCartCount = async (activeToken = token) => {
    if (!activeToken) {
      setCartCount(0);
      return;
    }
    try {
      const res = await fetch("http://localhost:3000/api/cart", {
        headers: { "Authorization": `Bearer ${activeToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setCartCount(data.reduce((sum, item) => sum + (item.quantity || 0), 0));
      } else if (res.status === 401) {
        handleAuthFail();
      } else {
        setCartCount(0);
      }
    } catch {
      setCartCount(0);
    }
  };

  useEffect(() => {
    refreshCartCount();
    if (token) {
      try {
        const decoded = JSON.parse(
          Buffer.from(token.split('.')[1] || '', 'base64').toString('utf-8')
        );
        const usernameFromToken = decoded?.sub || "";
        setUserName(usernameFromToken);
        sessionStorage.setItem('username', usernameFromToken);
      } catch {
        setUserName("");
        sessionStorage.removeItem('username');
      }
    } else {
      setUserName("");
      sessionStorage.removeItem('username');
    }
  }, [token]);

  const onLogout = () => {
    setToken(""); 
    sessionStorage.removeItem('token');
    setCartCount(0);
    setUserName("");
    sessionStorage.removeItem('username');
  }

  const handleAuthFail = () => {
    onLogout();
  }

  




  return (
    // <div>
    //   {!token ? (
    //     <Login onLogin={setToken}/>
    //   ) : (
    //     <>
    //     <Header token={token} onLogout={onLogout}/>
    //     <ProductList token={token}/>
    //     </> 
    //   )}
    // </div>
    <>
      <Header token={token} onLogout={onLogout} cartCount={cartCount} userName={userName}/>
      <main className='pt-16'>
        <Suspense fallback={<div>Loading...</div>}>
          <Routes>
            <Route path='/login' element={<Login onLogin={setToken}/>}/>
            <Route path='/' element={<Home token={token}/>}/>
            <Route path='/products' element={<ProductList token={token}/>}/>
            <Route path='/products/:sku' element={<ProductDetail token={token} onCartChange={refreshCartCount} onAuthFail={handleAuthFail}/>}/>
            <Route path='/signup' element={<Signup/>}/>
            <Route path='/account'
              element={
                token ? <Account/> :
                <Navigate to="/login"/>
              }
            />
            <Route path='/cart'
              element={
                token ? <Cart token={token} onCartChange={setCartCount} onAuthFail={handleAuthFail}/> :
                <Navigate to="/login"/>
              }
            />
            <Route path='/checkout'
              element={
                token ? <Checkout token={token} onAuthFail={handleAuthFail}/> :
                <Navigate to="/login"/>
              }
            />
          </Routes>
        </Suspense>
        
      </main>
    </>
  )
}

export default App
