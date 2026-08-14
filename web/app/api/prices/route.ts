import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

// 티커 1~6자(알파벳 대문자/점/하이픈), 콤마로 최대 100개까지 — 임의 문자열이
// FMP로 그대로 전달되어 API 쿼터를 소모하는 것을 막기 위한 입력 검증.
const TICKERS_PATTERN = /^[A-Z.\-]{1,6}(,[A-Z.\-]{1,6}){0,99}$/;

/**
 * FMP의 실시간(지연) 시세 엔드포인트로 최신가를 다시 불러온다.
 * "최신 종가"가 아니라 FMP가 제공하는 최신 체결가/지연 시세임에 유의.
 */
export async function GET(req: NextRequest) {
  const tickersParam = req.nextUrl.searchParams.get("tickers");
  if (!tickersParam) {
    return Response.json({ error: "tickers 파라미터가 필요합니다." }, { status: 400 });
  }
  if (!TICKERS_PATTERN.test(tickersParam)) {
    return Response.json({ error: "잘못된 티커 형식입니다." }, { status: 400 });
  }

  const key = process.env.FMP_API_KEY;
  if (!key) {
    return Response.json({ error: "서버에 FMP_API_KEY 환경변수가 설정되어 있지 않습니다." }, { status: 500 });
  }

  const url = `https://financialmodelingprep.com/api/v3/quote/${tickersParam}?apikey=${key}`;

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      return Response.json({ error: `FMP 조회 실패 (${res.status})` }, { status: 502 });
    }
    const rows: any[] = await res.json();

    const prices: Record<string, { price: number }> = {};
    for (const r of rows) {
      prices[r.symbol] = { price: r.price };
    }

    return Response.json({ as_of: new Date().toISOString(), prices });
  } catch (e: any) {
    return Response.json({ error: e.message ?? String(e) }, { status: 500 });
  }
}
