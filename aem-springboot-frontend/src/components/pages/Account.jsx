import { useState, useEffect } from "react";
import axios from "axios";

export default function AccountPage() {
  const [profile, setProfile] = useState({
    email: "",
    firstName: "",
    lastName: "",
    phone: "",
  });
  const [message, setMessage] = useState("");

  // Fetch user profile on mount
  useEffect(() => {
    async function fetchProfile() {
      try {
        const token = sessionStorage.getItem("token");
        const res = await axios.get("http://localhost:8081/account/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        setProfile(res.data);
      } catch {
        setMessage("Failed to load profile.");
      }
    }
    fetchProfile();
  }, []);

  // Handle form changes
  const handleChange = (e) => {
    setProfile({ ...profile, [e.target.name]: e.target.value });
  };

  // Save profile
  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const token = sessionStorage.getItem("token");
      await axios.put("http://localhost:8081/account/me", profile, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setMessage("Profile updated!");
    } catch {
      setMessage("Error updating profile.");
    }
  };

  return (
    <div className="flex justify-center items-center min-h-screen bg-gray-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white shadow-lg rounded-xl p-8 w-full max-w-lg"
      >
        <h2 className="text-xl font-bold mb-6">My Profile</h2>
        <div className="mb-4">
          <label className="block mb-1">First Name</label>
          <input
            className="w-full border border-gray-300 rounded px-3 py-2"
            name="firstName"
            value={profile.firstName}
            onChange={handleChange}
            required
          />
        </div>
        <div className="mb-4">
          <label className="block mb-1">Last Name</label>
          <input
            className="w-full border border-gray-300 rounded px-3 py-2"
            name="lastName"
            value={profile.lastName}
            onChange={handleChange}
            required
          />
        </div>
        <div className="mb-4">
          <label className="block mb-1">Email</label>
          <input
            className="w-full border border-gray-300 rounded px-3 py-2 bg-gray-100"
            name="email"
            value={profile.email}
            disabled
          />
        </div>
        <div className="mb-6">
          <label className="block mb-1">Phone</label>
          <input
            className="w-full border border-gray-300 rounded px-3 py-2"
            name="phone"
            value={profile.phone}
            onChange={handleChange}
          />
        </div>
        {message && (
          <div className="mb-4 text-center text-green-600">{message}</div>
        )}
        <button
          type="submit"
          className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700 transition"
        >
          Save Changes
        </button>
      </form>
    </div>
  );
}
