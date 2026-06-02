import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartTender AI",
  description: "מכרזים ממשלתיים רלוונטיים, אוטומטית",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="he" dir="rtl" className="h-full bg-gray-50">
      <body className="min-h-full text-gray-900">{children}</body>
    </html>
  );
}
