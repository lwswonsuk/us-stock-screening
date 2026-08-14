"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type FilteredRow = Record<string, string | number | null>;

interface FilteredPayload {
  columns: string[];
  column_labels_ko: Record<string, string>;
  results: FilteredRow[];
}

export default function FilteredDownloadButton({ passed, total }: { passed: number; total: number }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/filtered", { cache: "no-store" });
      if (!res.ok) throw new Error("필터통과 종목 데이터를 불러오지 못했습니다.");
      const data: FilteredPayload = await res.json();

      const XLSX = await import("xlsx");
      const rows = data.results.map((r) => {
        const out: Record<string, string | number | null> = {};
        for (const c of data.columns) {
          out[data.column_labels_ko[c] ?? c] = r[c];
        }
        return out;
      });
      const sheet = XLSX.utils.json_to_sheet(rows);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, sheet, "필터통과종목");
      XLSX.writeFile(wb, `필터통과종목_${data.results.length}종목.xlsx`);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant="secondary" className={cn("cursor-pointer select-none", loading && "opacity-60")} onClick={loading ? undefined : handleClick}>
        <Download className="mr-1 size-3" />
        {loading ? "다운로드 중…" : `필터 통과 ${passed} / ${total}`}
      </Badge>
      {error && <span className="text-xs text-destructive">{error}</span>}
    </span>
  );
}
