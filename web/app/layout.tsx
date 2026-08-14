import "./globals.css";

export const metadata = {
  title: "미국 주식 스크리닝 — US Stock Alpha",
  description: "S&P 500+400+600 종목 스크리닝 결과",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className="dark">
      <body className="min-h-screen bg-background font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
