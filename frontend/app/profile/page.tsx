"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import {
  api,
  getApiKey,
  type CompanyProfile,
  type ContractorClassification,
  type ExperienceRecord,
  type InsuranceCoverage,
} from "@/lib/api";

const INPUT_CLS =
  "border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500";
const ADD_BTN_CLS =
  "bg-gray-100 hover:bg-gray-200 rounded-lg text-sm px-3 py-2 transition-colors";
const DEL_BTN_CLS = "text-red-400 hover:text-red-600 transition-colors";

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
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className={`flex-1 ${INPUT_CLS}`}
        />
        <button type="button" onClick={add} className={ADD_BTN_CLS}>
          הוסף
        </button>
      </div>
    </div>
  );
}

function normalize(p: CompanyProfile): CompanyProfile {
  return {
    ...p,
    contractor_classifications: p.contractor_classifications ?? [],
    certifications: p.certifications ?? [],
    insurances: p.insurances ?? [],
    similar_public_projects: p.similar_public_projects ?? [],
    experience_years: p.experience_years ?? 0,
    equity_ils: p.equity_ils ?? null,
    employees_count: p.employees_count ?? null,
    annual_revenues: p.annual_revenues ?? {},
  };
}

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getApiKey()) { router.replace("/login"); return; }
    api.myProfile().then((p) => setProfile(normalize(p))).catch(() => setError("שגיאה בטעינת הפרופיל"));
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

  // ── annual revenues ────────────────────────────────────────────────────────

  function addRevenueYear() {
    const revenues = { ...profile!.annual_revenues };
    let year = new Date().getFullYear();
    while (String(year) in revenues && year > 1990) year--;
    if (!(String(year) in revenues)) {
      patch({ annual_revenues: { ...revenues, [String(year)]: 0 } });
    }
  }

  function updateRevenue(year: string, amount: number) {
    patch({ annual_revenues: { ...profile!.annual_revenues, [year]: amount } });
  }

  function removeRevenue(year: string) {
    const revenues = { ...profile!.annual_revenues };
    delete revenues[year];
    patch({ annual_revenues: revenues });
  }

  // ── contractor classifications ─────────────────────────────────────────────

  function addClassification() {
    patch({
      contractor_classifications: [
        ...profile!.contractor_classifications,
        { branch_code: "", group_letter: "א", financial_tier: 1, valid_until: null },
      ],
    });
  }

  function updateClassification(i: number, upd: Partial<ContractorClassification>) {
    patch({
      contractor_classifications: profile!.contractor_classifications.map((c, idx) =>
        idx === i ? { ...c, ...upd } : c
      ),
    });
  }

  function removeClassification(i: number) {
    patch({
      contractor_classifications: profile!.contractor_classifications.filter((_, idx) => idx !== i),
    });
  }

  // ── insurances ────────────────────────────────────────────────────────────

  function addInsurance() {
    patch({
      insurances: [
        ...profile!.insurances,
        { insurance_type: "third_party_liability", coverage_ils: 0, valid_until: null },
      ],
    });
  }

  function updateInsurance(i: number, upd: Partial<InsuranceCoverage>) {
    patch({
      insurances: profile!.insurances.map((ins, idx) =>
        idx === i ? { ...ins, ...upd } : ins
      ),
    });
  }

  function removeInsurance(i: number) {
    patch({ insurances: profile!.insurances.filter((_, idx) => idx !== i) });
  }

  // ── projects ──────────────────────────────────────────────────────────────

  function addProject() {
    patch({
      similar_public_projects: [
        ...profile!.similar_public_projects,
        { project_name: "", client_type: "public", value_ils: null, year: new Date().getFullYear(), domain_tags: [] },
      ],
    });
  }

  function updateProject(i: number, upd: Partial<ExperienceRecord>) {
    patch({
      similar_public_projects: profile!.similar_public_projects.map((p, idx) =>
        idx === i ? { ...p, ...upd } : p
      ),
    });
  }

  function removeProject(i: number) {
    patch({ similar_public_projects: profile!.similar_public_projects.filter((_, idx) => idx !== i) });
  }

  // ── render ────────────────────────────────────────────────────────────────

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
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">שם החברה</label>
                <input
                  value={profile.company_name}
                  onChange={(e) => patch({ company_name: e.target.value })}
                  className={`w-full ${INPUT_CLS}`}
                />
              </div>
            </section>

            {/* Financials */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">פיננסים</h2>
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">הון עצמי (₪)</label>
                    <input
                      type="number"
                      value={profile.equity_ils ?? ""}
                      onChange={(e) => patch({ equity_ils: e.target.value ? Number(e.target.value) : null })}
                      className={`w-full ${INPUT_CLS}`}
                      placeholder="1000000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">מספר עובדים</label>
                    <input
                      type="number"
                      value={profile.employees_count ?? ""}
                      onChange={(e) => patch({ employees_count: e.target.value ? Number(e.target.value) : null })}
                      className={`w-full ${INPUT_CLS}`}
                      placeholder="50"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">שנות ניסיון</label>
                    <input
                      type="number"
                      value={profile.experience_years}
                      onChange={(e) => patch({ experience_years: Number(e.target.value) })}
                      className={`w-full ${INPUT_CLS}`}
                      placeholder="10"
                      min={0}
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">מחזורים שנתיים</label>
                  <div className="flex flex-col gap-2">
                    {Object.entries(profile.annual_revenues)
                      .sort(([a], [b]) => Number(b) - Number(a))
                      .map(([year, amount]) => (
                        <div key={year} className="flex gap-2 items-center">
                          <input
                            type="number"
                            value={year}
                            readOnly
                            className={`w-24 ${INPUT_CLS} bg-gray-50`}
                          />
                          <input
                            type="number"
                            value={amount}
                            onChange={(e) => updateRevenue(year, Number(e.target.value))}
                            className={`flex-1 ${INPUT_CLS}`}
                            placeholder="סכום ₪"
                          />
                          <button type="button" onClick={() => removeRevenue(year)} className={`${DEL_BTN_CLS} text-xl leading-none`}>×</button>
                        </div>
                      ))}
                    <button type="button" onClick={addRevenueYear} className={`self-start ${ADD_BTN_CLS}`}>
                      + הוסף שנה
                    </button>
                  </div>
                </div>
              </div>
            </section>

            {/* Contractor classifications */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">סיווג קבלני</h2>
              <div className="flex flex-col gap-3">
                {profile.contractor_classifications.map((cls, i) => (
                  <div key={i} className="border border-gray-100 rounded-lg p-3 bg-gray-50 flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">קוד ענף</label>
                        <input
                          value={cls.branch_code}
                          onChange={(e) => updateClassification(i, { branch_code: e.target.value })}
                          className={`w-full ${INPUT_CLS}`}
                          placeholder="170"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">קבוצה</label>
                        <select
                          value={cls.group_letter}
                          onChange={(e) => updateClassification(i, { group_letter: e.target.value })}
                          className={`w-full ${INPUT_CLS}`}
                        >
                          {["א", "ב", "ג", "ד", "ה"].map((g) => (
                            <option key={g} value={g}>{g}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">דרגה פיננסית</label>
                        <select
                          value={cls.financial_tier}
                          onChange={(e) => updateClassification(i, { financial_tier: Number(e.target.value) })}
                          className={`w-full ${INPUT_CLS}`}
                        >
                          {[1, 2, 3, 4, 5].map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">בתוקף עד (אופציונלי)</label>
                        <input
                          type="date"
                          value={cls.valid_until ?? ""}
                          onChange={(e) => updateClassification(i, { valid_until: e.target.value || null })}
                          className={`w-full ${INPUT_CLS}`}
                        />
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <button type="button" onClick={() => removeClassification(i)} className={`${DEL_BTN_CLS} text-sm`}>
                        הסר סיווג
                      </button>
                    </div>
                  </div>
                ))}
                <button type="button" onClick={addClassification} className={`self-start ${ADD_BTN_CLS}`}>
                  + הוסף סיווג
                </button>
              </div>
            </section>

            {/* Certifications */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">תעודות ותקנים</h2>
              <TagInput
                label="תעודות ותקנים"
                values={profile.certifications}
                onChange={(v) => patch({ certifications: v })}
                placeholder='לדוגמה: "ISO 9001"'
              />
            </section>

            {/* Insurances */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">ביטוחים</h2>
              <div className="flex flex-col gap-3">
                {profile.insurances.map((ins, i) => (
                  <div key={i} className="border border-gray-100 rounded-lg p-3 bg-gray-50 flex flex-col gap-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">סוג ביטוח</label>
                        <select
                          value={ins.insurance_type}
                          onChange={(e) => updateInsurance(i, { insurance_type: e.target.value })}
                          className={`w-full ${INPUT_CLS}`}
                        >
                          <option value="third_party_liability">צד שלישי</option>
                          <option value="employer_liability">מעבידים</option>
                          <option value="professional">מקצועי</option>
                          <option value="other">אחר</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">סכום כיסוי (₪)</label>
                        <input
                          type="number"
                          value={ins.coverage_ils}
                          onChange={(e) => updateInsurance(i, { coverage_ils: Number(e.target.value) })}
                          className={`w-full ${INPUT_CLS}`}
                          placeholder="1000000"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">בתוקף עד (אופציונלי)</label>
                        <input
                          type="date"
                          value={ins.valid_until ?? ""}
                          onChange={(e) => updateInsurance(i, { valid_until: e.target.value || null })}
                          className={`w-full ${INPUT_CLS}`}
                        />
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <button type="button" onClick={() => removeInsurance(i)} className={`${DEL_BTN_CLS} text-sm`}>
                        הסר ביטוח
                      </button>
                    </div>
                  </div>
                ))}
                <button type="button" onClick={addInsurance} className={`self-start ${ADD_BTN_CLS}`}>
                  + הוסף ביטוח
                </button>
              </div>
            </section>

            {/* Projects experience */}
            <section className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4">ניסיון — פרויקטים קודמים</h2>
              <div className="flex flex-col gap-2">
                {profile.similar_public_projects.length > 0 && (
                  <div className="grid grid-cols-[1fr_7rem_7rem_5rem_2rem] gap-2 text-xs font-medium text-gray-500 px-1 mb-1">
                    <span>שם פרויקט</span>
                    <span>סוג לקוח</span>
                    <span>ערך (₪)</span>
                    <span>שנה</span>
                    <span></span>
                  </div>
                )}
                {profile.similar_public_projects.map((proj, i) => (
                  <div key={i} className="grid grid-cols-[1fr_7rem_7rem_5rem_2rem] gap-2 items-center">
                    <input
                      value={proj.project_name}
                      onChange={(e) => updateProject(i, { project_name: e.target.value })}
                      className={INPUT_CLS}
                      placeholder="שם הפרויקט"
                    />
                    <select
                      value={proj.client_type}
                      onChange={(e) => updateProject(i, { client_type: e.target.value })}
                      className={INPUT_CLS}
                    >
                      <option value="public">ציבורי</option>
                      <option value="municipal">עירוני</option>
                      <option value="government">ממשלתי</option>
                      <option value="private">פרטי</option>
                    </select>
                    <input
                      type="number"
                      value={proj.value_ils ?? ""}
                      onChange={(e) => updateProject(i, { value_ils: e.target.value ? Number(e.target.value) : null })}
                      className={INPUT_CLS}
                      placeholder="0"
                    />
                    <input
                      type="number"
                      value={proj.year}
                      onChange={(e) => updateProject(i, { year: Number(e.target.value) })}
                      className={INPUT_CLS}
                      min={1990}
                      max={2030}
                    />
                    <button type="button" onClick={() => removeProject(i)} className={`${DEL_BTN_CLS} text-xl leading-none`}>×</button>
                  </div>
                ))}
                <button type="button" onClick={addProject} className={`self-start ${ADD_BTN_CLS} mt-1`}>
                  + הוסף פרויקט
                </button>
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
                      className={`w-full ${INPUT_CLS}`}
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
                      className={`w-full ${INPUT_CLS}`}
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
                    className={`w-32 ${INPUT_CLS}`}
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
                    className={`w-full ${INPUT_CLS}`}
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
