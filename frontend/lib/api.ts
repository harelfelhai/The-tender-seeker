const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { apiKey?: string } = {}
): Promise<T> {
  const { apiKey, ...rest } = options;
  const key = apiKey ?? getApiKey();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(key ? { "X-API-Key": key } : {}),
      ...rest.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json() as Promise<T>;
}

// ── auth ──────────────────────────────────────────────────────────────────────

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("api_key");
}

export function setApiKey(key: string) {
  localStorage.setItem("api_key", key);
}

export function clearApiKey() {
  localStorage.removeItem("api_key");
}

export function verifyKey(key: string) {
  return request<{ company_id: string; company_name: string }>("/auth/me", {
    apiKey: key,
  });
}

// ── types ─────────────────────────────────────────────────────────────────────

export interface TenderMatch {
  tender_id: string;
  title_he: string;
  publisher_he: string;
  is_eligible: boolean;
  compatibility_score: number;
  relevance_score: number;
  final_score: number;
  summary_he: string;
}

export interface MatchAllResponse {
  company_id: string;
  total: number;
  matches: TenderMatch[];
}

export interface CriterionResult {
  criterion_id: string;
  description_he: string;
  mandatory: boolean;
  passed: boolean;
  actual_value: unknown;
  required_value: unknown;
  category: string;
  page: number | null;
  quote_he: string | null;
}

export interface RelevanceFactor {
  name: string;
  score: number;
  explanation_he: string;
}

export interface TenderMatchDetail extends TenderMatch {
  breakdown: CriterionResult[];
  relevance_factors: RelevanceFactor[];
}

export interface ContractorClassification {
  branch_code: string;
  group_letter: string;
  financial_tier: number;
  valid_until: string | null;
}

export interface ExperienceRecord {
  project_name: string;
  client_type: string;
  value_ils: number | null;
  year: number;
  domain_tags: string[];
}

export interface InsuranceCoverage {
  insurance_type: string;
  coverage_ils: number;
  valid_until: string | null;
}

export interface CompanyProfile {
  company_name: string;
  company_reg_id: string | null;
  annual_revenues: Record<string, number>;
  equity_ils: number | null;
  contractor_classifications: ContractorClassification[];
  certifications: string[];
  experience_years: number;
  similar_public_projects: ExperienceRecord[];
  insurances: InsuranceCoverage[];
  employees_count: number | null;
  domains: string[];
  operating_regions: string[];
  preferred_client_types: string[];
  min_project_value_ils: number | null;
  max_project_value_ils: number | null;
  harvest_keywords: string[];
  preferred_tender_types: string[];
  min_days_to_deadline: number;
  notification_email: string | null;
  notification_enabled: boolean;
  [key: string]: unknown;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const api = {
  me: () => request<{ company_id: string; company_name: string }>("/auth/me"),
  allMatches: () => request<MatchAllResponse>("/match"),
  tenderMatch: (id: string) => request<TenderMatchDetail>(`/match/${id}`),
  myProfile: () => request<CompanyProfile>("/companies/me"),
  updateProfile: (profile: CompanyProfile) =>
    request<CompanyProfile>("/companies/me", {
      method: "PUT",
      body: JSON.stringify(profile),
    }),
};
