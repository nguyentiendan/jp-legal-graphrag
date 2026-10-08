import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "JP Legal GraphRAG",
  description: "Dense + Graph retrieval cho văn bản pháp luật Nhật Bản",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
