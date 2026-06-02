"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  getApiKey,
  InterviewSuggestions,
  ProfileDiff,
  SampleTender,
  CompanyProfile,
} from "@/lib/api";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M ₪`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K ₪`;
  return `${n} ₪`;
}

// ── Chip with remove button ───────────────────────────────────────────────────

function Chip({
  label,
  checked,
  onChange,
  color = "blue",
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  color?: "blue" | "red" | "green";
}) {
  const colors = {
    blue: checked ? "bg-blue-100 text-blue-800 border-blue-300" : "bg-gray-100 text-gray-400 border-gray-200 line-through",
    red: checked ? "bg-red-100 text-red-800 border-red-300" : "bg-gray-100 text-gray-400 border-gray-200 line-through",
    green: checked ? "bg-green-100 text-green-800 border-green-300" : "bg-gray-100 text-gray-400 border-gray-200 line-through",
  };
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-sm font-medium transition-all ${colors[color]}`}
    >
      {label}
      {checked ? (
        <span className="text-xs opacity-60 hover:opacity-100">✕</span>
      ) : (
        <span className="text-xs opacity-60">↩</span>
      )}
    </button>
  );
}

// ── Step indicator ────────────────────────────────────────────────────────────

function Steps({ current }: { current: number }) {
  const steps = ["פרטי בסיס", "ראיון", "דוגמאות", "אישור"];
  return (
    <div className="flex items-center gap-0 mb-10">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
            i === current ? "bg-blue-600 text-white" :
            i < current ? "bg-green-100 text-green-700" :
            "bg-gray-100 text-gray-400"
          }`}>
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
              i < current ? "bg-green-500 text-white" : i === current ? "bg-white text-blue-600" : "bg-gray-300 text-gray-500"
            }`}>
              {i < current ? "✓" : i + 1}
            </span>
            {s}
          </div>
          {i < steps.length - 1 && (
            <div className={`w-8 h-0.5 ${i < current ? "bg-green-300" : "bg-gray-200"}`} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── STEP 1: Hard fields summary ───────────────────────────────────────────────

function Step1({ profile, onNext }: { profile: CompanyProfile; onNext: () => void }) {
  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 mb-1">פרטי בסיס</h2>
      <p className="text-sm text-gray-500 mb-6">וודא שהפרטים הקשיחים מלאים לפני שממשיכים</p>

      <div className="bg-gray-50 rounded-xl border border-gray-200 p-5 space-y-3 text-sm mb-6">
        <Row label="שם החברה" value={profile.company_name} />
        <Row label="ח.פ." value={profile.company_reg_id || "—"} />
        <Row label="ניסיון (שנים)" value={profile.experience_years || "—"} />
        <Row label="עובדים" value={profile.employees_count || "—"} />
        <Row label="תחומים" value={profile.domains.join(", ") || "—"} />
        <Row label="אזורים" value={profile.operating_regions.join(", ") || "—"} />
        <Row label="תקציב מינ׳" value={fmt(profile.min_project_value_ils)} />
        <Row label="תקציב מקס׳" value={fmt(profile.max_project_value_ils)} />
      </div>

      <div className="flex gap-3">
        <button
          onClick={() => window.open("/profile", "_blank")}
          className="px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
        >
          עדכן פרטים
        </button>
        <button
          onClick={onNext}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          המשך לראיון ←
        </button>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900 text-left">{String(value)}</span>
    </div>
  );
}

// ── STEP 2: Interview ─────────────────────────────────────────────────────────

function Step2({
  onDone,
}: {
  onDone: (suggestions: InterviewSuggestions) => void;
}) {
  const [answers, setAnswers] = useState<{ question: string; answer: string }[]>([]);
  const [currentQ, setCurrentQ] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [totalQ, setTotalQ] = useState(4);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    fetchNext([]);
  }, []);

  useEffect(() => {
    textareaRef.current?.focus();
  }, [currentQ]);

  async function fetchNext(ans: typeof answers) {
    setLoading(true);
    try {
      const res = await api.onboarding.interviewStep(ans);
      setTotalQ(res.total_questions);
      if (res.done && res.suggestions) {
        onDone(res.suggestions);
      } else {
        setCurrentQ(res.next_question);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!answer.trim() || !currentQ) return;
    const newAnswers = [...answers, { question: currentQ, answer: answer.trim() }];
    setAnswers(newAnswers);
    setAnswer("");
    setCurrentQ(null);
    await fetchNext(newAnswers);
  }

  const progress = answers.length / totalQ;

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 mb-1">ראיון קצר</h2>
      <p className="text-sm text-gray-500 mb-6">
        {answers.length}/{totalQ} שאלות — עוזר לנו לאפיין את החברה שלך בצורה מדויקת
      </p>

      {/* Progress bar */}
      <div className="h-1.5 bg-gray-100 rounded-full mb-6">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      {/* Previous answers */}
      {answers.length > 0 && (
        <div className="space-y-4 mb-6">
          {answers.map((qa, i) => (
            <div key={i} className="bg-gray-50 rounded-lg p-4 text-sm">
              <div className="text-gray-500 mb-1">{qa.question}</div>
              <div className="text-gray-900 font-medium">{qa.answer}</div>
            </div>
          ))}
        </div>
      )}

      {/* Current question */}
      {loading && !currentQ ? (
        <div className="text-gray-400 text-sm animate-pulse">טוען שאלה...</div>
      ) : currentQ ? (
        <div>
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4">
            <p className="text-blue-900 font-medium text-sm">{currentQ}</p>
          </div>
          <textarea
            ref={textareaRef}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) handleSubmit();
            }}
            placeholder="הקלד את תשובתך כאן... (Ctrl+Enter לשליחה)"
            rows={4}
            className="w-full border border-gray-300 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            dir="rtl"
          />
          <div className="flex justify-end mt-3">
            <button
              onClick={handleSubmit}
              disabled={!answer.trim() || loading}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:bg-blue-300"
            >
              {loading ? "שולח..." : "המשך ←"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── STEP 3: Sample tenders review ────────────────────────────────────────────

type Verdict = "yes" | "no" | null;

function Step3({
  onDone,
}: {
  onDone: (feedbacks: { raw_tender_id: string; title: string; publisher: string | null; subjects: string[]; budget_ils: number | null; relevant: boolean; reason: string }[]) => void;
}) {
  const [samples, setSamples] = useState<SampleTender[]>([]);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.onboarding.getSamples(15).then((s) => {
      setSamples(s);
      setLoading(false);
    });
  }, []);

  const answered = Object.values(verdicts).filter((v) => v !== null).length;

  function handleSubmit() {
    const feedbacks = samples
      .filter((s) => verdicts[s.id] !== null && verdicts[s.id] !== undefined)
      .map((s) => ({
        raw_tender_id: s.id,
        title: s.title_he,
        publisher: s.publisher_he,
        subjects: s.subjects,
        budget_ils: s.estimated_budget_ils,
        relevant: verdicts[s.id] === "yes",
        reason: reasons[s.id] || "",
      }));
    onDone(feedbacks);
  }

  if (loading) return <div className="text-gray-400 text-sm animate-pulse">טוען מכרזים לדוגמה...</div>;

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 mb-1">סקירת מכרזים לדוגמה</h2>
      <p className="text-sm text-gray-500 mb-6">
        סמן האם כל מכרז היה מעניין אותך. ענית על {answered}/{samples.length}.
      </p>

      <div className="space-y-3 mb-6">
        {samples.map((t) => {
          const v = verdicts[t.id];
          return (
            <div
              key={t.id}
              className={`border rounded-xl p-4 transition-colors ${
                v === "yes" ? "border-green-300 bg-green-50" :
                v === "no" ? "border-red-200 bg-red-50" :
                "border-gray-200 bg-white"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-900 text-sm leading-snug mb-1">
                    {t.title_he || "—"}
                  </div>
                  <div className="flex flex-wrap gap-1.5 text-xs text-gray-500">
                    {t.publisher_he && <span>{t.publisher_he}</span>}
                    {t.estimated_budget_ils != null && (
                      <span className="text-gray-400">· {fmt(t.estimated_budget_ils)}</span>
                    )}
                    {t.subjects.slice(0, 2).map((s) => (
                      <span key={s} className="bg-gray-100 px-1.5 py-0.5 rounded">{s}</span>
                    ))}
                    {!t.filter_passed && (
                      <span className="bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded">נדחה בסינון</span>
                    )}
                  </div>
                </div>

                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => setVerdicts((p) => ({ ...p, [t.id]: "yes" }))}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                      v === "yes"
                        ? "bg-green-500 text-white border-green-500"
                        : "border-gray-300 text-gray-500 hover:border-green-400 hover:text-green-600"
                    }`}
                  >
                    מעניין ✓
                  </button>
                  <button
                    onClick={() => setVerdicts((p) => ({ ...p, [t.id]: "no" }))}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                      v === "no"
                        ? "bg-red-500 text-white border-red-500"
                        : "border-gray-300 text-gray-500 hover:border-red-400 hover:text-red-600"
                    }`}
                  >
                    לא מעניין ✕
                  </button>
                </div>
              </div>

              {v !== null && (
                <input
                  value={reasons[t.id] || ""}
                  onChange={(e) => setReasons((p) => ({ ...p, [t.id]: e.target.value }))}
                  placeholder={v === "yes" ? "למה כן? (אופציונלי)" : "למה לא? (אופציונלי)"}
                  className="mt-2 w-full text-xs border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                  dir="rtl"
                />
              )}
            </div>
          );
        })}
      </div>

      <button
        onClick={handleSubmit}
        disabled={answered < 5}
        className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:bg-blue-300"
      >
        {answered < 5 ? `ענה על לפחות 5 (${answered}/5)` : "נתח את הפידבק ←"}
      </button>
    </div>
  );
}

// ── STEP 4: Review & apply diff ───────────────────────────────────────────────

function Step4({
  diff,
  summaryHe,
  interviewSuggestions,
  profile,
  onApply,
  applying,
}: {
  diff: ProfileDiff;
  summaryHe: string;
  interviewSuggestions: InterviewSuggestions | null;
  profile: CompanyProfile;
  onApply: (selected: Partial<ProfileDiff> & { interview: InterviewSuggestions | null }) => void;
  applying: boolean;
}) {
  // Track which items the user keeps (checked = keep)
  const [kept, setKept] = useState<Record<string, Record<string, boolean>>>(() => {
    const init: Record<string, Record<string, boolean>> = {};
    for (const [key, arr] of Object.entries(diff)) {
      if (Array.isArray(arr)) {
        init[key] = Object.fromEntries((arr as string[]).map((v) => [v, true]));
      }
    }
    if (interviewSuggestions) {
      for (const [key, arr] of Object.entries(interviewSuggestions)) {
        if (Array.isArray(arr)) {
          init[`interview_${key}`] = Object.fromEntries((arr as string[]).map((v) => [v, true]));
        }
      }
    }
    return init;
  });

  function toggle(section: string, item: string) {
    setKept((p) => ({ ...p, [section]: { ...p[section], [item]: !p[section][item] } }));
  }

  function getKeptArr(section: string): string[] {
    return Object.entries(kept[section] || {}).filter(([, v]) => v).map(([k]) => k);
  }

  function handleApply() {
    const selected: Partial<ProfileDiff> = {
      add_domains: getKeptArr("add_domains"),
      remove_domains: getKeptArr("remove_domains"),
      add_keywords: getKeptArr("add_keywords"),
      remove_keywords: getKeptArr("remove_keywords"),
      add_negative_patterns: getKeptArr("add_negative_patterns"),
      add_regions: getKeptArr("add_regions"),
      add_client_types: getKeptArr("add_client_types"),
    };

    const interview = interviewSuggestions
      ? {
          suggested_domains: getKeptArr("interview_suggested_domains"),
          suggested_keywords: getKeptArr("interview_suggested_keywords"),
          suggested_regions: getKeptArr("interview_suggested_regions"),
          suggested_client_types: getKeptArr("interview_suggested_client_types"),
          suggested_negatives: getKeptArr("interview_suggested_negatives"),
          summary_he: interviewSuggestions.summary_he,
        }
      : null;

    onApply({ ...selected, interview });
  }

  const Section = ({
    title,
    section,
    color,
    empty,
  }: {
    title: string;
    section: string;
    color: "blue" | "red" | "green";
    empty?: string;
  }) => {
    const items = Object.keys(kept[section] || {});
    if (items.length === 0) return empty ? <p className="text-xs text-gray-400">{empty}</p> : null;
    return (
      <div className="mb-4">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</div>
        <div className="flex flex-wrap gap-2">
          {items.map((item) => (
            <Chip
              key={item}
              label={item}
              checked={kept[section][item]}
              onChange={() => toggle(section, item)}
              color={color}
            />
          ))}
        </div>
      </div>
    );
  };

  const hasInterviewData = interviewSuggestions && (
    ["suggested_domains", "suggested_keywords", "suggested_regions", "suggested_client_types", "suggested_negatives"]
      .some((k) => (interviewSuggestions[k as keyof InterviewSuggestions] as string[])?.length > 0)
  );

  return (
    <div>
      <h2 className="text-xl font-bold text-gray-900 mb-1">אישור עדכונים לפרופיל</h2>
      <p className="text-sm text-gray-500 mb-2">{summaryHe}</p>
      <p className="text-xs text-gray-400 mb-6">לחץ על פריט כדי להסירו לפני האישור</p>

      {hasInterviewData && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-xl">
          <div className="text-sm font-semibold text-blue-800 mb-3">מהראיון</div>
          <Section title="תחומים להוסיף" section="interview_suggested_domains" color="blue" />
          <Section title="מילות מפתח להוסיף" section="interview_suggested_keywords" color="blue" />
          <Section title="אזורים להוסיף" section="interview_suggested_regions" color="blue" />
          <Section title="סוגי לקוחות" section="interview_suggested_client_types" color="blue" />
          <Section title="לא מעניין (negative)" section="interview_suggested_negatives" color="red" />
        </div>
      )}

      <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-xl">
        <div className="text-sm font-semibold text-green-800 mb-3">מסקירת המכרזים</div>
        {diff.explanation_he && (
          <p className="text-xs text-gray-600 mb-3">{diff.explanation_he}</p>
        )}
        <Section title="תחומים להוסיף" section="add_domains" color="green" empty="אין" />
        <Section title="מילות מפתח להוסיף" section="add_keywords" color="green" empty="אין" />
        <Section title="אזורים להוסיף" section="add_regions" color="green" empty="אין" />
        <Section title="סוגי לקוחות להוסיף" section="add_client_types" color="green" empty="אין" />
        <Section title="דפוסים שליליים להוסיף" section="add_negative_patterns" color="red" empty="אין" />
        <Section title="מילות מפתח להסיר" section="remove_keywords" color="red" empty="אין" />
        <Section title="תחומים להסיר" section="remove_domains" color="red" empty="אין" />
      </div>

      <button
        onClick={handleApply}
        disabled={applying}
        className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:bg-blue-300"
      >
        {applying ? "מעדכן פרופיל..." : "אשר ועדכן פרופיל ←"}
      </button>
    </div>
  );
}

// ── Main wizard ───────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [interviewSuggestions, setInterviewSuggestions] = useState<InterviewSuggestions | null>(null);
  const [diff, setDiff] = useState<{ diff: ProfileDiff; summary_he: string } | null>(null);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getApiKey()) { router.push("/login"); return; }
    api.myProfile().then(setProfile).catch(() => router.push("/login"));
  }, []);

  async function handleFeedbackDone(
    feedbacks: { raw_tender_id: string; title: string; publisher: string | null; subjects: string[]; budget_ils: number | null; relevant: boolean; reason: string }[]
  ) {
    try {
      const result = await api.onboarding.analyzeFeedback(feedbacks);
      setDiff(result);
      setStep(3);
    } catch {
      setError("שגיאה בניתוח הפידבק");
    }
  }

  async function handleApply(selected: Partial<ProfileDiff> & { interview: InterviewSuggestions | null }) {
    if (!profile) return;
    setApplying(true);
    setError("");

    try {
      const updated = { ...profile };

      // Apply feedback diff
      if (selected.add_domains?.length) {
        updated.domains = [...new Set([...updated.domains, ...selected.add_domains])];
      }
      if (selected.remove_domains?.length) {
        updated.domains = updated.domains.filter((d) => !selected.remove_domains!.includes(d));
      }
      if (selected.add_keywords?.length) {
        updated.harvest_keywords = [...new Set([...updated.harvest_keywords, ...selected.add_keywords])];
      }
      if (selected.remove_keywords?.length) {
        updated.harvest_keywords = updated.harvest_keywords.filter((k) => !selected.remove_keywords!.includes(k));
      }
      if (selected.add_regions?.length) {
        updated.operating_regions = [...new Set([...updated.operating_regions, ...selected.add_regions])];
      }
      if (selected.add_client_types?.length) {
        updated.preferred_client_types = [...new Set([...updated.preferred_client_types, ...selected.add_client_types])];
      }

      // Apply interview suggestions
      if (selected.interview) {
        if (selected.interview.suggested_domains?.length) {
          updated.domains = [...new Set([...updated.domains, ...selected.interview.suggested_domains])];
        }
        if (selected.interview.suggested_keywords?.length) {
          updated.harvest_keywords = [...new Set([...updated.harvest_keywords, ...selected.interview.suggested_keywords])];
        }
        if (selected.interview.suggested_regions?.length) {
          updated.operating_regions = [...new Set([...updated.operating_regions, ...selected.interview.suggested_regions])];
        }
        if (selected.interview.suggested_client_types?.length) {
          updated.preferred_client_types = [...new Set([...updated.preferred_client_types, ...selected.interview.suggested_client_types])];
        }
      }

      await api.updateProfile(updated);
      router.push("/dashboard");
    } catch {
      setError("שגיאה בעדכון הפרופיל");
      setApplying(false);
    }
  }

  if (!profile) {
    return <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">טוען...</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-6 py-12">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">הגדרת פרופיל</h1>
          <p className="text-gray-500 mt-1 text-sm">3 שלבים קצרים כדי שהמערכת תכיר את החברה שלך</p>
        </div>

        <Steps current={step} />

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="bg-white rounded-2xl border border-gray-200 p-8 shadow-sm">
          {step === 0 && (
            <Step1 profile={profile} onNext={() => setStep(1)} />
          )}
          {step === 1 && (
            <Step2
              onDone={(suggestions) => {
                setInterviewSuggestions(suggestions);
                setStep(2);
              }}
            />
          )}
          {step === 2 && (
            <Step3 onDone={handleFeedbackDone} />
          )}
          {step === 3 && diff && (
            <Step4
              diff={diff.diff}
              summaryHe={diff.summary_he}
              interviewSuggestions={interviewSuggestions}
              profile={profile}
              onApply={handleApply}
              applying={applying}
            />
          )}
        </div>
      </div>
    </div>
  );
}
