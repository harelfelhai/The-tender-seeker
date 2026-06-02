"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import NavBar from "@/components/NavBar";
import { api, getApiKey, type MatchAllResponse, type TenderMatch } from "@/lib/api";

function ScoreBadge({ score, eligible }: { score: number; eligible: boolean }) {
  if (!eligible)
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-red-50 text-red-700">
        ✕ לא כשיר
      </span>
    );
  const pct = Math.round(score * 100);
  const color =
    pct >= 70 ? "bg-green-50 text-green-700" : pct >= 40 ? "bg-yellow-50 text-yellow-700" : "bg-gray-100 text-gray-600";
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${color}`}>
      ✓ כשיר · {pct}%
    </span>
  );
}

function TenderCard({ tender }: { tender: TenderMatch }) {
  return (
    <Link
      href={`/tender/${tender.tender_id}`}
      className="block bg-white rounded-xl border border-gray-200 p-5 hover:border-blue-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 leading-snug mb-1 truncate">
            {tender.title_he}
          </h3>
          <p className="text-sm text-gray-500 mb-3">{tender.publisher_he}</p>
          <p className="text-sm text-gray-600 leading-relaxed line-clamp-2">
            {tender.summary_he}
          </p>
        </div>
        <ScoreBadge score={tender.final_score} eligible={tender.is_eligible} />
      </div>
    </Link>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [data, setData] = useState<MatchAllResponse | null>(null);
  const [error, setError] = useState("");
  const [companyName, setCompanyName] = useState<string>();

  useEffect(() => {
    if (!getApiKey()) { router.replace("/login"); return; }
    api.me().then((me) => setCompanyName(me.company_name)).catch(() => {});
    api.allMatches()
      .then(setData)
      .catch(() => setError("שגיאה בטעינת המכרזים"));
  }, [router]);

  const eligible = data?.matches.filter((m) => m.is_eligible) ?? [];
  const ineligible = data?.matches.filter((m) => !m.is_eligible) ?? [];

  return (
    <div className="min-h-screen">
      <NavBar companyName={companyName} />
      <main className="max-w-3xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-bold text-gray-900">מכרזים מתאימים</h1>
          {data && (
            <span className="text-sm text-gray-500">
              {eligible.length} כשירים מתוך {data.total}
            </span>
          )}
        </div>

        {!data && !error && (
          <div className="flex justify-center py-20 text-gray-400">טוען...</div>
        )}

        {error && (
          <div className="bg-red-50 text-red-700 rounded-xl px-5 py-4 text-sm">{error}</div>
        )}

        {data && data.total === 0 && (
          <div className="text-center py-20 text-gray-400">
            <p className="text-lg">אין מכרזים עדיין</p>
            <p className="text-sm mt-1">העלה מכרז דרך ה-API כדי להתחיל</p>
          </div>
        )}

        {eligible.length > 0 && (
          <section className="mb-8">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
              כשירים — {eligible.length}
            </h2>
            <div className="flex flex-col gap-3">
              {eligible.map((t) => <TenderCard key={t.tender_id} tender={t} />)}
            </div>
          </section>
        )}

        {ineligible.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
              לא כשירים — {ineligible.length}
            </h2>
            <div className="flex flex-col gap-3 opacity-60">
              {ineligible.map((t) => <TenderCard key={t.tender_id} tender={t} />)}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
