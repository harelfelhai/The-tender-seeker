"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, RawTender, HarvestResult, getApiKey } from "@/lib/api";

const STATUS_LABEL: Record<string, string> = {
  PENDING_ANALYSIS: "ממתין לניתוח",
  pending_analysis: "ממתין לניתוח",
  ANALYZED: "נותח",
  analyzed: "נותח",
  REJECTED: "נדחה",
  rejected: "נדחה",
  ERROR: "שגיאה",
  error: "שגיאה",
};

const STATUS_COLOR: Record<string, string> = {
  PENDING_ANALYSIS: "bg-yellow-100 text-yellow-800",
  pending_analysis: "bg-yellow-100 text-yellow-800",
  ANALYZED: "bg-green-100 text-green-800",
  analyzed: "bg-green-100 text-green-800",
  REJECTED: "bg-gray-100 text-gray-600",
  rejected: "bg-gray-100 text-gray-600",
  ERROR: "bg-red-100 text-red-700",
  error: "bg-red-100 text-red-700",
};

type FilterStatus = "ALL" | "PENDING_ANALYSIS" | "ANALYZED" | "REJECTED" | "ERROR";

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M ₪`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K ₪`;
  return `${n} ₪`;
}

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return s.slice(0, 10);
}

export default function RawTendersPage() {
  const router = useRouter();
  const [tenders, setTenders] = useState<RawTender[]>([]);
  const [filter, setFilter] = useState<FilterStatus>("ALL");
  const [loading, setLoading] = useState(true);
  const [harvesting, setHarvesting] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [harvestResult, setHarvestResult] = useState<HarvestResult | null>(null);
  const [reEvalResult, setReEvalResult] = useState<{ promoted: number; evaluated: number } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getApiKey()) { router.push("/login"); return; }
    load();
  }, []);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api.rawTenders(undefined, 500);
      setTenders(data);
    } catch {
      setError("שגיאה בטעינת הנתונים");
    } finally {
      setLoading(false);
    }
  }

  async function runHarvest() {
    setHarvesting(true);
    setHarvestResult(null);
    setError("");
    try {
      const res = await api.triggerHarvest();
      setHarvestResult(res);
      await load();
    } catch {
      setError("שגיאה בהרצת הקצירה");
    } finally {
      setHarvesting(false);
    }
  }

  async function runReEvaluate() {
    setReEvaluating(true);
    setReEvalResult(null);
    setError("");
    try {
      const key = getApiKey();
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/harvest/re-evaluate?limit=2000`, {
        method: "POST",
        headers: { "X-API-Key": key ?? "" },
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setReEvalResult({ promoted: data.promoted_to_pending, evaluated: data.evaluated });
      await load();
    } catch {
      setError("שגיאה בהרצת Re-evaluate");
    } finally {
      setReEvaluating(false);
    }
  }

  const norm = (s: string) => s.toUpperCase();
  const visible = filter === "ALL" ? tenders : tenders.filter((t) => norm(t.status) === filter);

  const counts = {
    ALL: tenders.length,
    PENDING_ANALYSIS: tenders.filter((t) => norm(t.status) === "PENDING_ANALYSIS").length,
    ANALYZED: tenders.filter((t) => norm(t.status) === "ANALYZED").length,
    REJECTED: tenders.filter((t) => norm(t.status) === "REJECTED").length,
    ERROR: tenders.filter((t) => norm(t.status) === "ERROR").length,
  };

  const FILTER_TABS: { key: FilterStatus; label: string }[] = [
    { key: "ALL", label: "הכל" },
    { key: "PENDING_ANALYSIS", label: "ממתין לניתוח" },
    { key: "ANALYZED", label: "נותח" },
    { key: "REJECTED", label: "נדחה" },
    { key: "ERROR", label: "שגיאה" },
  ];

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">מכרזים שנקצרו</h1>
            <p className="text-sm text-gray-500 mt-0.5">raw tenders — לפני ניתוח LLM</p>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => router.push("/dashboard")}
              className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-100"
            >
              ← חזרה לדשבורד
            </button>
            <button
              onClick={runReEvaluate}
              disabled={reEvaluating}
              title="הפעל פילטר מחדש על מכרזים שנדחו לפי הפרופיל הנוכחי"
              className="px-4 py-2 text-sm bg-amber-600 hover:bg-amber-700 disabled:bg-amber-300 text-white rounded-lg font-medium"
            >
              {reEvaluating ? "מעריך מחדש..." : "Re-evaluate"}
            </button>
            <button
              onClick={runHarvest}
              disabled={harvesting}
              className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-lg font-medium"
            >
              {harvesting ? "קוצר..." : "הרץ קצירה"}
            </button>
          </div>
        </div>

        {/* Re-evaluate result banner */}
        {reEvalResult && (
          <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 flex gap-6">
            <span>הוערכו מחדש: <b>{reEvalResult.evaluated}</b></span>
            <span>קודמו לניתוח: <b>{reEvalResult.promoted}</b></span>
          </div>
        )}

        {/* Harvest result banner */}
        {harvestResult && (
          <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800 flex gap-6">
            <span>נקצרו: <b>{harvestResult.fetched}</b></span>
            <span>חדשים: <b>{harvestResult.new}</b></span>
            <span>כפולים: <b>{harvestResult.duplicates}</b></span>
            <span>ממתינים לניתוח: <b>{harvestResult.pending_analysis}</b></span>
            <span>נדחו: <b>{harvestResult.rejected}</b></span>
            {harvestResult.errors > 0 && <span className="text-red-600">שגיאות: <b>{harvestResult.errors}</b></span>}
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: "סה״כ נקצרו", value: counts.ALL, color: "text-gray-900" },
            { label: "ממתינים לניתוח", value: counts.PENDING_ANALYSIS, color: "text-yellow-700" },
            { label: "נותחו", value: counts.ANALYZED, color: "text-green-700" },
            { label: "נדחו", value: counts.REJECTED, color: "text-gray-500" },
          ].map((s) => (
            <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4">
              <div className={`text-3xl font-bold ${s.color}`}>{s.value}</div>
              <div className="text-sm text-gray-500 mt-1">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 mb-4 bg-white border border-gray-200 rounded-lg p-1 w-fit">
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                filter === tab.key
                  ? "bg-blue-600 text-white"
                  : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {tab.label}
              <span className={`mr-1.5 text-xs ${filter === tab.key ? "text-blue-200" : "text-gray-400"}`}>
                ({counts[tab.key]})
              </span>
            </button>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="p-12 text-center text-gray-400">טוען...</div>
          ) : visible.length === 0 ? (
            <div className="p-12 text-center text-gray-400">
              {tenders.length === 0
                ? "לא נקצרו מכרזים עדיין — לחץ «הרץ קצירה»"
                : "אין מכרזים בסטטוס זה"}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-24">סטטוס</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600">כותרת</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-40">מפרסם</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-28">סוג</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-28">תקציב</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-24">דדליין</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-16">PDF</th>
                    <th className="text-right px-4 py-3 font-medium text-gray-600 w-28">נקצר</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visible.map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[t.status] ?? "bg-gray-100 text-gray-600"}`}>
                          {STATUS_LABEL[t.status] ?? t.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-900 line-clamp-2 max-w-xs" title={t.title_he}>
                          {t.title_he || "—"}
                        </div>
                        {t.subjects.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {t.subjects.slice(0, 3).map((s) => (
                              <span key={s} className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                                {s}
                              </span>
                            ))}
                            {t.subjects.length > 3 && (
                              <span className="text-xs text-gray-400">+{t.subjects.length - 3}</span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">{t.publisher_he || "—"}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{t.tender_type || "—"}</td>
                      <td className="px-4 py-3 text-gray-600 text-xs font-mono">{fmt(t.estimated_budget_ils)}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{fmtDate(t.deadline)}</td>
                      <td className="px-4 py-3 text-center">
                        {t.pdf_urls.length > 0 ? (
                          <a
                            href={t.pdf_urls[0]}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-500 hover:text-blue-700"
                            title="פתח PDF"
                          >
                            📄
                          </a>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{fmtDate(t.harvested_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {visible.length > 0 && (
          <p className="text-xs text-gray-400 mt-2 text-left">
            מציג {visible.length} רשומות
          </p>
        )}
      </div>
    </div>
  );
}
