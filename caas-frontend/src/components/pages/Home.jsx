import { Navigate } from "react-router-dom"
import Header from "../Header"
const Home = ({token}) => {
    return(
        <>
        <h1>Welcome to HopNShoppe</h1>
        {token ?
        <Navigate to="/products"/>
        :
        // <p>Please log in <a className="text-amber-500" href="/login">here</a> to browse our products</p>
        <Navigate to="/login"/>
        }
        
        </>
    )
}

export default Home