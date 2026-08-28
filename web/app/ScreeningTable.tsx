"use client";

import { useMemo, useState } from "react";
import { ArrowUpDown, ArrowUp, ArrowDown, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import StockProfileDialog, { StockProfile } from "./StockProfileDialog";

type ResultRow = Record<string, string | number | null> & { profile?: StockProfile | null };

const TWO_DECIMAL_RIGHT_ALIGN = new Set([
  "per", "pbr", "roe_3y_avg", "interest_coverage", "buyback_rate_pct",
  "div_yield", "payout_ratio_pct", "pct_above_52w_low_pct",
]);
const FOUR_DECIMAL_RIGHT_ALIGN = new Set(["score"]);
const RIGHT_ALIGN_ONLY = new Set(["price", "mktcap_usd"]);

export default function ScreeningTable({
  columns,
  labels,
  rows,
  defaultSortKey = "score",
  defaultSortDir = "desc",
}: {
  columns: string[];
  labels: Record<string, string>;
  rows: ResultRow[];
  defaultSortKey?: string;
  defaultSortDir?: "asc" | "desc";
}) {
  const [sortKey, setSortKey] = useState<string>(defaultSortKey);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(defaultSortDir);
  const [liveRows, setLiveRows] = useState<ResultRow[]>(rows);
  const [priceAsOf, setPriceAsOf] = useState<string | null>(null);
  const [priceLoading, setPriceLoading] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [dialogRow, setDialogRow] = useState<ResultRow | null>(null);

  async function refreshPrices() {
    setPriceLoading(true);
    setPriceError(null);
    try {
      const tickers = rows.map((r) => String(r.stock_code)).join(",");
      const res = await fetch(`/api/prices?tickers=${tickers}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "시세 조회 실패");

      setLiveRows(
        rows.map((r) => {
          const ticker = String(r.stock_code);
          const live = data.prices[ticker];
          if (!live) return r;
          return { ...r, price: live.price } as ResultRow;
        })
      );
      setPriceAsOf(data.as_of);
    } catch (e: any) {
      setPriceError(e.message ?? String(e));
    } finally {
      setPriceLoading(false);
    }
  }

  const sorted = useMemo(() => {
    const copy = [...liveRows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return copy.slice(0, 50);
  }, [liveRows, sortKey, sortDir]);

  function onSort(col: string) {
    if (col === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(col);
      setSortDir("desc");
    }
  }

  function SortIcon({ col }: { col: string }) {
    if (sortKey !== col) return <ArrowUpDown className="ml-1 inline size-3 opacity-40" />;
    return sortDir === "asc" ? <ArrowUp className="ml-1 inline size-3" /> : <ArrowDown className="ml-1 inline size-3" />;
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={refreshPrices} disabled={priceLoading}>
          <RefreshCw className={cn("size-3.5", priceLoading && "animate-spin")} />
          {priceLoading ? "불러오는 중…" : "최신 종가 새로고침"}
        </Button>
        {priceAsOf && (
          <span className="text-xs text-muted-foreground">시세 기준일: {priceAsOf}</span>
        )}
        {priceError && <span className="text-xs text-destructive">{priceError}</span>}
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-10">#</TableHead>
              {columns.map((col) => (
                <TableHead key={col} className={cn("cursor-pointer select-none", alignClass(col))} onClick={() => onSort(col)}>
                  {labels[col] ?? col}
                  <SortIcon col={col} />
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row, i) => (
              <TableRow key={(row.stock_code as string) ?? i}>
                <TableCell className="text-muted-foreground">{i + 1}</TableCell>
                {columns.map((col) => (
                  <TableCell key={col} className={alignClass(col)}>
                    {col === "name" ? (
                      <button
                        type="button"
                        className="underline decoration-dotted underline-offset-2 hover:text-primary"
                        onClick={() => setDialogRow(row)}
                      >
                        {formatValue(row[col], col)}
                      </button>
                    ) : (
                      formatValue(row[col], col)
                    )}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <StockProfileDialog
        open={dialogRow !== null}
        onOpenChange={(open) => !open && setDialogRow(null)}
        stockName={dialogRow ? String(dialogRow.stock_code ?? "") : ""}
        profile={dialogRow?.profile}
      />
    </div>
  );
}

function alignClass(col: string): string {
  if (TWO_DECIMAL_RIGHT_ALIGN.has(col) || FOUR_DECIMAL_RIGHT_ALIGN.has(col) || RIGHT_ALIGN_ONLY.has(col)) {
    return "text-right";
  }
  return "";
}

function formatValue(v: string | number | null, col?: string) {
  if (v === null || v === undefined) return "-";
  if (typeof v === "number") {
    if (col === "mktcap_usd") {
      return "$" + v.toLocaleString("en-US", { maximumFractionDigits: 0 });
    }
    if (col === "price") {
      return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    if (col && FOUR_DECIMAL_RIGHT_ALIGN.has(col)) {
      return v.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
    }
    if (col && TWO_DECIMAL_RIGHT_ALIGN.has(col)) {
      return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(3);
  }
  return v;
}
