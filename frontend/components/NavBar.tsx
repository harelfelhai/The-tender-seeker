"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearApiKey } from "@/lib/api";

export default function NavBar({ companyName }: { companyName?: string }) {
  const pathname = usePathname();
  const router = useRouter();

  function logout() {
    clearApiKey();
    router.push("/login");
  }

  const links = [
    { href: "/dashboard", label: "מכרזים" },
    { href: "/profile", label: "פרופיל החברה" },
  ];

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3">
      <div className="max-w-5xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="font-bold text-blue-700 text-lg">SmartTender AI</span>
          <div className="flex gap-4">
            {links.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className={`text-sm font-medium px-3 py-1.5 rounded-md transition-colors ${
                  pathname.startsWith(l.href)
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                }`}
              >
                {l.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {companyName && (
            <span className="text-sm text-gray-500">{companyName}</span>
          )}
          <button
            onClick={logout}
            className="text-sm text-gray-500 hover:text-red-600 transition-colors"
          >
            התנתק
          </button>
        </div>
      </div>
    </nav>
  );
}
