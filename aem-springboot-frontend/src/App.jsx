import { lazy, Suspense, useState } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from '/vite.svg'
import './App.css'
import Header from './components/Header'
import { Navigate, Route, Routes } from 'react-router-dom'
import Home from './components/pages/Home'
import Signup from './components/pages/Signup'
import Account from './components/pages/Account'

function App() {
  const [count, setCount] = useState(0)
  const [token, setToken] = useState(sessionStorage.getItem('token'));

  const ProductList = lazy(() => import('./components/pages/ProductList'));

  const ProductDetail = lazy(() => import('./components/pages/ProductDetail'));

  const Login = lazy(() => import('./components/pages/Login'));

  const onLogout = () => {
    setToken(""); 
    sessionStorage.removeItem('token');
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
      <Header token={token} onLogout={onLogout}/>
      <main className='pt-16'>
        <Suspense fallback={<div>Loading...</div>}>
          <Routes>
            <Route path='/login' element={<Login onLogin={setToken}/>}/>
            <Route path='/' element={<Home token={token}/>}/>
            <Route path='/products' element={<ProductList token={token}/>}/>
            <Route path='/products/:sku' element={<ProductDetail token={token}/>}/>
            <Route path='/signup' element={<Signup/>}/>
            <Route path='/account'
              element={
                token ? <Account/> :
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
