import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const TICKERS_PATTERN = /^[A-Z.\-]{1,6}(,[A-Z.\-]{1,6}){0,99}$/;

async function fetchOneQuote(ticker: string, key: string): Promise<[string, number | null]> {
  try {
    const res = await fetch(
      `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(ticker)}&token=${key}`,
      { cache: "no-store" }
    );
    if (!res.ok) return [ticker, null];
    const data = await res.json();
    return [ticker, typeof data.c === "number" ? data.c : null];
  } catch {
    return [ticker, null];
  }
}

export async function GET(req: NextRequest) {
  const tickersParam = req.nextUrl.searchParams.get("tickers");
  if (!tickersParam || !TICKERS_PATTERN.test(tickersParam)) {
    return Response.json({ error: "잘못된 티커 형식입니다." }, { status: 400 });
  }

  const key = process.env.FINNHUB_API_KEY;
  if (!key) {
    return Response.json({ error: "서버에 FINNHUB_API_KEY 환경변수가 설정되어 있지 않습니다." }, { status: 500 });
  }

  const tickers = tickersParam.split(",");
  const prices: Record<string, { price: number }> = {};

  const BATCH_SIZE = 10;
  for (let i = 0; i < tickers.length; i += BATCH_SIZE) {
    const batch = tickers.slice(i, i + BATCH_SIZE);
    const results = await Promise.all(batch.map((t) => fetchOneQuote(t, key)));
    for (const [ticker, price] of results) {
      if (price !== null) prices[ticker] = { price };
    }
  }

  return Response.json({ as_of: new Date().toISOString(), prices });
}
