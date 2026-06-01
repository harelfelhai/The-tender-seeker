"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import NavBar from "@/components/NavBar";
import { api, getApiKey, type TenderMatchDetail, type CriterionResult } from "@/lib/api";

const CATEGORY_HE: Record<string, string> = {
  financial: "פיננסי",
  classification: "סיווג קבלני",
  experience: "ניסיון",
  certification: "הסמכות",
  insurance: "ביטוח",
  legal: "משפטי",
  personnel: "כוח אדם",
  other: "אחר",
};

function CriterionRow({ c }: { c: CriterionResult }) {
  const [open, setOpen] = useState(false);
  const icon = c.passed ? "✓" : c.mandatory ? "✕" : "–";
  const iconColor = c.passed
    ? "text-green-600"
    : c.mandatory
    ? "text-red-600"
    : "text-gray-400";

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-right transition-colors"
      >
        <span className={`text-base font-bold shrink-0 ${iconColor}`}>{icon}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900">{c.description_he}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {CATEGORY_HE[c.category] ?? c.category}
            {c.mandatory ? " · חובה" : " · יתרון"}
            {c.page ? ` · עמ׳ ${c.page}` : ""}
          </p>
        </div>
        <span className="text-gray-400 text-xs shrink-0">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 text-sm space-y-2">
          {c.quote_he && (
            <blockquote className="border-r-2 border-blue-300 pr-3 text-gray-600 italic">
              {c.quote_he}
            </blockquote>
          )}
          <div className="flex gap-4 text-xs text-gray-500">
            {c.required_value !== null && c.required_value !== undefined && (
              <span>נדרש: <strong className="text-gray-700">{String(c.required_value)}</strong></span>
            )}
            {c.actual_value !== null && c.actual_value !== undefined && (
              <span>קיים: <strong className={c.passed ? "text-green-700" : "text-red-700"}>{String(c.actual_value)}</strong></span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TenderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<TenderMatchDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getApiKey()) { router.replace("/login"); return; }
    api.tenderMatch(id)
      .then(setData)
      .catch(() => setError("שגיאה בטעינת המכרז"));
  }, [id, router]);

  const mandatory = data?.breakdown.filter((c) => c.mandatory) ?? [];
  const optional = data?.breakdown.filter((c) => !c.mandatory) ?? [];
  const passedMandatory = mandatory.filter((c) => c.passed).length;

  return (
    <div className="min-h-screen">
      <NavBar />
      <main className="max-w-3xl mx-auto px-4 py-8">
        <Link href="/dashboard" className="text-sm text-blue-600 hover:underline mb-6 block">
          ← חזרה למכרזים
        </Link>

        {!data && !error && (
          <div className="flex justify-center py-20 text-gray-400">טוען...</div>
        )}
        {error && (
          <div className="bg-red-50 text-red-700 rounded-xl px-5 py-4 text-sm">{error}</div>
        )}

        {data && (
          <>
            {/* Header */}
            <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <h1 className="text-xl font-bold text-gray-900 leading-snug">
                    {data.title_he}
                  </h1>
                  <p className="text-sm text-gray-500 mt-1">{data.publisher_he}</p>
                </div>
                <div className="shrink-0">
                  {data.is_eligible ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold bg-green-50 text-green-700">
                      ✓ כשיר
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold bg-red-50 text-red-700">
                      ✕ לא כשיר
                    </span>
                  )}
                </div>
              </div>
              <p className="text-sm text-gray-600 leading-relaxed">{data.summary_he}</p>

              {/* Score bar */}
              <div className="mt-4 pt-4 border-t border-gray-100 flex items-center gap-6 text-sm">
                <div>
                  <span className="text-gray-500">תנאי סף: </span>
                  <span className="font-semibold">
                    {passedMandatory}/{mandatory.length}
                  </span>
                </div>
                {data.is_eligible && (
                  <div>
                    <span className="text-gray-500">רלוונטיות: </span>
                    <span className="font-semibold">
                      {Math.round(data.relevance_score * 100)}%
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Relevance factors */}
            {data.is_eligible && data.relevance_factors.length > 0 && (
              <section className="mb-6">
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
                  גורמי רלוונטיות
                </h2>
                <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
                  {data.relevance_factors.map((f, i) => (
                    <div key={i} className="flex items-center gap-4 px-4 py-3">
                      <div className="w-24 bg-gray-100 rounded-full h-2 shrink-0">
                        <div
                          className="bg-blue-500 h-2 rounded-full"
                          style={{ width: `${Math.round(f.score * 100)}%` }}
                        />
                      </div>
                      <span className="text-sm text-gray-700">{f.explanation_he}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Mandatory criteria */}
            <section className="mb-4">
              <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
                תנאי סף ({mandatory.length})
              </h2>
              <div className="flex flex-col gap-2">
                {mandatory.map((c) => <CriterionRow key={c.criterion_id} c={c} />)}
              </div>
            </section>

            {/* Optional criteria */}
            {optional.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
                  יתרונות ({optional.length})
                </h2>
                <div className="flex flex-col gap-2">
                  {optional.map((c) => <CriterionRow key={c.criterion_id} c={c} />)}
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  );
}
