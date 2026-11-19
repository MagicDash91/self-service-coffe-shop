import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kopi Pagi · Pesan Mandiri",
  description: "Kios pesan mandiri kedai kopi dengan suara dan sentuh (prototipe)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
