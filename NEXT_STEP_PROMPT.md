# פרומפט לצ'אט הבא — השלמת פרופיל הכשירות

---

## הקשר

אתה עובד על SmartTender AI — SaaS B2B לשוק הישראלי שעוקב אחרי מכרזים ממשלתיים.
**קרא קודם את `CLAUDE.md` בשורש הפרויקט** — הוא מכיל את כל ההקשר הטכני.

---

## הבעיה שצריך לפתור

דף הפרופיל הנוכחי (`frontend/app/profile/page.tsx`) מכסה רק:
- פילטרי קצירה (מילות מפתח, תחומים, אזורים, טווח תקציב, ימים לדדליין)
- הגדרות התראות (אימייל + toggle)

**חסר לחלוטין — נתוני כשירות:**
```
annual_revenues          # dict[year → amount]
equity_ils               # optional float
contractor_classifications  # list of {branch_code, group_letter, financial_tier, valid_until}
certifications           # list of strings (e.g. "ISO 9001")
experience_years         # int
similar_public_projects  # list of {project_name, client_type, value_ils, year, domain_tags}
insurances               # list of {insurance_type, coverage_ils, valid_until}
employees_count          # optional int
```

בלי השדות האלה — מנוע ההתאמה בצד שרת תמיד מחזיר "לא כשיר" כי אין לו מה להשוות.

---

## מה צריך לבנות

### 1. עדכן `frontend/lib/api.ts`
הוסף לממשק `CompanyProfile` את כל השדות החסרים:
```typescript
export interface ContractorClassification {
  branch_code: string;
  group_letter: string;
  financial_tier: number;
  valid_until: string | null;
}

export interface ExperienceRecord {
  project_name: string;
  client_type: string;           // "public" | "municipal" | "government" | "private"
  value_ils: number | null;
  year: number;
  domain_tags: string[];
}

export interface InsuranceCoverage {
  insurance_type: string;        // "third_party_liability" | "employer_liability" | "professional"
  coverage_ils: number;
  valid_until: string | null;
}

// הוסף לתוך CompanyProfile:
annual_revenues: Record<string, number>;    // כבר קיים — ודא שלא חסר
equity_ils: number | null;
contractor_classifications: ContractorClassification[];
certifications: string[];
experience_years: number;
similar_public_projects: ExperienceRecord[];
insurances: InsuranceCoverage[];
employees_count: number | null;
```

### 2. עדכן `frontend/app/profile/page.tsx`
הוסף sections חדשים בטופס (אחרי "פרטים כלליים", לפני "פילטרי קצירה"):

#### Section: פיננסים
- שדה `equity_ils` — number input
- שדה `employees_count` — number input
- שדה `experience_years` — number input
- מחזורים שנתיים — טבלה עם שורות `{שנה, סכום}`, כפתור "הוסף שנה", כפתור מחיקה לכל שורה

#### Section: סיווג קבלני
רשימה של כרטיסיות, כל אחת עם:
- `branch_code` — text input (קוד ענף, למשל "170")
- `group_letter` — select: א / ב / ג / ד / ה
- `financial_tier` — select: 1 / 2 / 3 / 4 / 5
- `valid_until` — date input (אופציונלי)
- כפתור הסרה לכל כרטיסייה
- כפתור "הוסף סיווג"

#### Section: תעודות ותקנים
- TagInput קיים (שדה `certifications`) — לדוגמה: "ISO 9001", "ISO 14001"

#### Section: ביטוחים
רשימה של כרטיסיות, כל אחת עם:
- `insurance_type` — select: third_party_liability / employer_liability / professional / other
- labels בעברית: "צד שלישי" / "מעבידים" / "מקצועי" / "אחר"
- `coverage_ils` — number input
- `valid_until` — date input (אופציונלי)
- כפתור הסרה

#### Section: ניסיון — פרויקטים קודמים
טבלה קומפקטית (לא כרטיסיות — יכולים להיות הרבה), כל שורה:
- `project_name` — text input
- `client_type` — select: public / municipal / government / private
- `value_ils` — number input (אופציונלי)
- `year` — number input
- כפתור מחיקה
- כפתור "הוסף פרויקט"

---

## הנחיות עיצוב

- שמור על אותו סגנון כמו הסections הקיימים: `bg-white rounded-xl border border-gray-200 p-5`
- label בעברית מעל כל שדה, text-sm font-medium text-gray-700
- inputs: `border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500`
- כפתורי הוסף: `bg-gray-100 hover:bg-gray-200 rounded-lg text-sm px-3 py-2`
- כפתורי מחיקה: `text-red-400 hover:text-red-600` עם אייקון ×
- הכל RTL, הצ'אט עם המשתמש בעברית

---

## patch() helper קיים

הפונקציה `patch(fields)` כבר קיימת ב-profile/page.tsx ומעדכנת את ה-state:
```typescript
function patch(fields: Partial<CompanyProfile>) {
  setProfile((p) => p ? { ...p, ...fields } : p);
}
```
השתמש בה לכל השדות החדשים.

---

## אחרי הבנייה

1. הרץ `cd frontend && npm run build` — ודא zero TypeScript errors
2. Commit + push לענף `claude/zealous-heisenberg-30hwu`
3. PR #1 כבר קיים (draft) — הוא יתעדכן אוטומטית

---

## מה לא לגעת בו

- קוד backend — ה-API כבר תומך בכל השדות האלה ב-`PUT /companies/me`
- `NavBar.tsx`, `dashboard/page.tsx`, `tender/[id]/page.tsx` — לא צריך שינוי
- הsections הקיימים בפרופיל (פרטים כלליים, פילטרי קצירה, התראות) — שמור אותם
