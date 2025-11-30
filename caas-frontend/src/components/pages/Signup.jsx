import { useState } from "react";
import axios from "axios";

export default function Signup() {
  const [form, setForm] = useState({
    email: "", firstName: "", lastName: "", phone: "", password: ""
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleChange = e => setForm({ ...form, [e.target.name]: e.target.value });

  const handleSubmit = async e => {
    e.preventDefault();
    setError(""); setSuccess("");
    if(e.target[0].name === "email"){
        let isValidEmail = validateEmail(e.target[0].value);
        if(isValidEmail){
            try {
                await axios.post("http://localhost:8081/auth/signup", form);
                setSuccess("Account created! You can now log in ");
                setForm({ email: "", firstName: "", lastName: "", phone: "", password: "" });
                } catch (err) {
                setError(err.response?.data || "Registration failed");
                }
        }
    }
    
  };

  const validateEmail = (email) => {
    let regexEmailep = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
    if(!regexEmailep.test(email)){
        setError("Please provide a valid Email");
        return false;
    }
    return true
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <form className="bg-white p-8 rounded-xl shadow-md w-full max-w-md" onSubmit={handleSubmit}>
        <h2 className="text-2xl font-semibold text-center mb-6">Sign Up</h2>
        {["email", "firstName", "lastName", "phone", "password"].map(field =>
          <div className="mb-4" key={field}>
            <label className="block mb-1 capitalize">{field}{field !== "phone" && <span className="text-red-500">*</span>}</label>
            <input
              className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:border-blue-500"
              type={field === "password" ? "password" : (field === "email" ? "email" : "text")}
              name={field}
              value={form[field]}
              onChange={handleChange}
              required={field !== "phone"}
            />
          </div>
        )}
        {error && <div className="text-red-600 mb-3">{error}</div>}
        {success && <div className="text-green-600 mb-3">{success}<a className="text-blue-500 hover:underline" href="/login">here</a></div>}
        <button
          type="submit"
          className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 transition"
        >
          Create Account
        </button>
      </form>
    </div>
  );
}
