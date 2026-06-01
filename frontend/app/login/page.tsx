"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setApiKey, verifyKey, ApiError } from "@/lib/api";

export default function LoginPage() {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyKey(key.trim());
      setApiKey(key.trim());
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("מפתח API לא תקין");
      } else {
        setError("שגיאה בהתחברות — בדוק שהשרת פועל");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-10 w-full max-w-md">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">SmartTender AI</h1>
        <p className="text-gray-500 text-sm mb-8">הכנס את מפתח ה-API שלך כדי להתחבר</p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              מפתח API
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="sk-st-..."
              className="w-full border border-gray-300 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              dir="ltr"
              autoComplete="off"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={!key.trim() || loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {loading ? "מתחבר..." : "התחבר"}
          </button>
        </form>

        <p className="text-xs text-gray-400 mt-6 text-center">
          מפתח ה-API מוצג פעם אחת בעת הרישום דרך ה-API
        </p>
      </div>
    </div>
  );
}
