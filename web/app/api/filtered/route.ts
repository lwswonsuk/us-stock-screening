import fs from "fs";
import path from "path";

export const dynamic = "force-static";

export async function GET() {
  const filePath = path.join(process.cwd(), "data", "filtered_full.json");
  if (!fs.existsSync(filePath)) {
    return Response.json({ error: "필터통과 데이터가 아직 생성되지 않았습니다." }, { status: 404 });
  }
  const raw = fs.readFileSync(filePath, "utf-8");
  return new Response(raw, { headers: { "Content-Type": "application/json" } });
}
