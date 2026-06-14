import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/shell/sidebar";
import MobileNav from "@/components/shell/mobile-nav";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NexaGold — Trading IA sur l'or",
  description:
    "Plateforme de trading algorithmique sur l'or (XAU/USD) pilotée par IA",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="fr"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full bg-base font-sans text-ink">
        <Sidebar />
        <MobileNav />
        <main className="lg:pl-60">
          <div className="mx-auto max-w-7xl px-5 py-6 sm:px-8 sm:py-8">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
