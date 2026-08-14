import { createHmac, timingSafeEqual } from "crypto";

function isAdminRequest(req: Request): boolean {
  const adminPassword = process.env.ADMIN_PASSWORD;
  if (!adminPassword) return false;
  const cookieHeader = req.headers.get("cookie") ?? "";
  const match = cookieHeader.match(/admin_session=([^;]+)/);
  if (!match) return false;
  const expected = createHmac("sha256", adminPassword).update("admin").digest("hex");
  const a = Buffer.from(match[1]);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

export async function POST(req: Request) {
  if (!isAdminRequest(req)) {
    return Response.json({ error: "관리자 인증이 필요합니다." }, { status: 401 });
  }

  const token = process.env.GH_PAT;
  const owner = process.env.GH_OWNER;
  const repo = process.env.GH_REPO;

  if (!token || !owner || !repo) {
    return Response.json(
      { error: "서버 환경변수(GH_PAT / GH_OWNER / GH_REPO)가 설정되어 있지 않습니다. Vercel 프로젝트 설정에서 등록해주세요." },
      { status: 500 }
    );
  }

  let forceFinance = false;
  try {
    const body = await req.json();
    forceFinance = Boolean(body?.forceFinance);
  } catch {
    // body 없이 호출된 경우 기본값 사용
  }

  const res = await fetch(
    `https://api.github.com/repos/${owner}/${repo}/actions/workflows/daily-screen.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main", inputs: { force_finance: String(forceFinance) } }),
    }
  );

  if (!res.ok) {
    const text = await res.text();
    return Response.json({ error: `GitHub 워크플로우 실행 요청 실패 (${res.status}): ${text}` }, { status: 502 });
  }

  return Response.json({
    ok: true,
    message: "업데이트가 요청되었습니다. GitHub Actions에서 실행 중이며, 완료 후 자동으로 사이트가 재배포됩니다 (보통 2~10분 정도 걸립니다).",
  });
}
