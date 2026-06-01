"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import { api, getApiKey, type CompanyProfile } from "@/lib/api";

function TagInput({
  label,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [input, setInput] = useState("");

  function add() {
    const v = input.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setInput("");
  }

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <div className="flex flex-wrap gap-2 mb-2">
        {values.map((v) => (
          <span
            key={v}
            className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 text-sm px-2.5 py-1 rounded-full"
          >
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="text-blue-400 hover:text-blue-700 leading-none"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={placeholder}
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          type="button"
          onClick={add}
          className="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium transition-colors"
        >
          הוסף
        </button>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getApiKey()) { router.replace("/login"); return; }
    api.myProfile().then(setProfile).catch(() => setError("שגיאה בטעינת הפרופיל"));
  }, [router]);

  function patch(fields: Partial<CompanyProfile>) {
    setProfile((p) => p ? { ...p, ...fields } : p);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!profile) return;
    setSaving(true);
    setError("");
    try {
      await api.updateProfile(profile);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch {
      setError("שגיאה בשמירה — נסה שוב");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen">
      <NavBar companyName={profile?.company_name} />
      <main className="max-w-2xl mx-auto px-4 py-8">
        <h1 className="text-xl font-bold text-gray-900 mb-6">פרופיל החברה</h1>

        {!profile && !error && (
          <div className="text-gray-400 text-center py-20">טוען...</div>
        )}
        {error && (
          <div className="bg-red-50 text-red-700 rounded-xl px-5 py-4 text-sm mb-4">{error}</div>
        )}

        {profile && (
          <form onSubmit={handleSave} className="flex flex-col gap-6">

            {/* Basic info */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">פרטים כלליים</h2>
              <div className="flex flex-col gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">שם החברה</label>
                  <input
                    value={profile.company_name}
                    onChange={(e) => patch({ company_name: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
            </section>

            {/* Harvest filters */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-1">פילטרי קצירה</h2>
              <p className="text-sm text-gray-500 mb-4">
                מכרזים מה-API ייסוננו לפי הפרמטרים האלו לפני ניתוח AI
              </p>
              <div className="flex flex-col gap-4">
                <TagInput
                  label="מילות מפתח (כותרת / נושאים)"
                  values={profile.harvest_keywords}
                  onChange={(v) => patch({ harvest_keywords: v })}
                  placeholder='לדוגמה: "מיזוג אוויר"'
                />
                <TagInput
                  label="תחומי פעילות"
                  values={profile.domains}
                  onChange={(v) => patch({ domains: v })}
                  placeholder='לדוגמה: "תשתיות"'
                />
                <TagInput
                  label="אזורי פעילות"
                  values={profile.operating_regions}
                  onChange={(v) => patch({ operating_regions: v })}
                  placeholder='לדוגמה: "מרכז"'
                />
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      מינימום ערך פרויקט (₪)
                    </label>
                    <input
                      type="number"
                      value={profile.min_project_value_ils ?? ""}
                      onChange={(e) => patch({ min_project_value_ils: e.target.value ? Number(e.target.value) : null })}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="500000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      מקסימום ערך פרויקט (₪)
                    </label>
                    <input
                      type="number"
                      value={profile.max_project_value_ils ?? ""}
                      onChange={(e) => patch({ max_project_value_ils: e.target.value ? Number(e.target.value) : null })}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="10000000"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    מינימום ימים לדדליין
                  </label>
                  <input
                    type="number"
                    value={profile.min_days_to_deadline}
                    onChange={(e) => patch({ min_days_to_deadline: Number(e.target.value) })}
                    min={0}
                    className="w-32 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
            </section>

            {/* Notifications */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">התראות</h2>
              <div className="flex flex-col gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    כתובת אימייל להתראות
                  </label>
                  <input
                    type="email"
                    value={profile.notification_email ?? ""}
                    onChange={(e) => patch({ notification_email: e.target.value || null })}
                    placeholder="company@example.com"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    dir="ltr"
                  />
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={profile.notification_enabled}
                    onChange={(e) => patch({ notification_enabled: e.target.checked })}
                    className="w-4 h-4 rounded accent-blue-600"
                  />
                  <span className="text-sm text-gray-700">התראות פעילות</span>
                </label>
              </div>
            </section>

            <div className="flex items-center gap-3">
              <button
                type="submit"
                disabled={saving}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-medium px-6 py-2.5 rounded-lg text-sm transition-colors"
              >
                {saving ? "שומר..." : "שמור שינויים"}
              </button>
              {saved && <span className="text-sm text-green-600">✓ נשמר</span>}
            </div>
          </form>
        )}
      </main>
    </div>
  );
}
