"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export default function UpdateControls() {
  const [forceFinance, setForceFinance] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);

  async function handleUpdate() {
    setLoading(true);
    setMessage(null);
    try {
      const res = await fetch("/api/update-finance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ forceFinance }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "요청 실패");
      setMessage({ text: data.message, error: false });
    } catch (e: any) {
      setMessage({ text: e.message ?? String(e), error: true });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mb-5 py-4">
      <CardContent className="flex flex-wrap items-center gap-4">
        <Button onClick={handleUpdate} disabled={loading} size="sm">
          <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          {loading ? "요청 중…" : "스크리닝 업데이트 실행"}
        </Button>

        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <Checkbox checked={forceFinance} onCheckedChange={(v) => setForceFinance(v === true)} />
          재무데이터도 강제로 새로 받기 (평소엔 체크 안 해도 됨, 몇 분 더 걸림)
        </label>

        {message && (
          <span className={cn("text-xs", message.error ? "text-destructive" : "text-green-500")}>
            {message.text}
          </span>
        )}
      </CardContent>
    </Card>
  );
}
