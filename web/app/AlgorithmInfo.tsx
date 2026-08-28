"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Info, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function AlgorithmInfo() {
  const [open, setOpen] = useState(false);

  return (
    <div className="mb-5 space-y-3">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm">
            <Info className="size-3.5" />
            이 스크리닝은 어떤 기준으로 종목을 골랐나요?
            {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </Button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <Card className="mt-3 py-5">
            <CardContent className="space-y-4 text-sm leading-relaxed text-foreground/90">
              <p className="text-muted-foreground">
                핵심 아이디어:{" "}
                <b className="text-foreground">실적·경쟁력은 괜찮은데 주가만 안 오른 종목을 찾아서 모아두고 기다린다.</b>
              </p>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">1단계 — 하드 필터 (자동 제외 기준)</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li>시가총액 $100M 이상 (상한 없음)</li>
                  <li>ROE 5% 미만 제외</li>
                  <li>최근 영업이익(TTM 기준) 적자 제외</li>
                  <li>최근 3개월 수익률 +60% 이상인 테마 급등 종목 제외</li>
                </ul>
                <p className="mt-2 text-muted-foreground">
                  ※ 부채비율 하드 필터는 폐지되었습니다. 부채 건전성은 이자보상배율로 바꿔
                  아래 체력 점수의 랭킹 요소로만 반영됩니다(하드 배제는 하지 않음).
                </p>
              </div>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">2단계 — 4대 팩터 종합 점수</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li><b className="text-foreground">체력 (30%)</b> — ROE 수준·안정성, 영업이익률, 이자보상배율(부채 건전성), 매출 성장</li>
                  <li><b className="text-foreground">가격 (28%)</b> — PER·PBR 저평가 정도</li>
                  <li><b className="text-foreground">★괴리 (27%, 핵심 팩터)</b> — 실적은 개선되는데 주가는 빠진 정도. 52주 낙폭 비중을 확대해 저점 근접도가 더 크게 반영됩니다.</li>
                  <li><b className="text-foreground">환원여력 (15%)</b> — 배당 확대 여력 + <b className="text-foreground">자사주매입률</b>(발행주식수 감소율). 자사주 매입 비중을 확대해 가장 중요한 환원 지표로 반영됩니다.</li>
                </ul>
                <p className="mt-2 text-muted-foreground">
                  각 팩터는 전체 종목 대비 백분위로 점수화되며, 위 가중치로 합산해{" "}
                  <b className="text-foreground">종합점수</b>를 만듭니다.
                </p>
              </div>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">데이터 기준</h4>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                  <li>시세/재무데이터: Finnhub API + Wikipedia(지수 구성종목)</li>
                  <li>대상: S&P 500 + S&P 400(중형) + S&P 600(소형) 종목</li>
                </ul>
                <p className="mt-2 text-muted-foreground">
                  ROE 변동성, 매출 성장률, 순현금 비율 등 일부 세부 지표는 Finnhub 무료
                  티어에서 3년치 히스토리를 직접 제공하지 않아 현재는 중립값으로 처리됩니다. 그만큼 랭킹은
                  ROE 절대수준, 영업이익률, 이자보상배율, PER/PBR, 배당, 자사주매입률 등 실제로 확보된
                  지표에 더 크게 의존합니다. 자사주매입률은 직전 분기 대비 발행주식수 감소율로 추정한
                  값이라 데이터가 처음 쌓이는 한 분기 동안은 중립값(신규 종목)으로 처리됩니다.
                </p>
              </div>

              <div>
                <h4 className="mb-2 font-semibold text-foreground">52주 신저가 근접 종목</h4>
                <p className="text-muted-foreground">
                  하드 필터를 통과한 종목 중 52주 저점에 가장 가까운 종목만 별도로 추려
                  표 하단에 따로 보여줍니다. 종합점수 랭킹과 무관하게 저점 근접도만으로 정렬됩니다.
                </p>
              </div>
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>

      <Alert className="border-muted-foreground/20 bg-transparent py-2.5">
        <ShieldAlert />
        <AlertDescription className="text-xs text-muted-foreground">
          이 페이지의 정보는 참고용 데이터이며 투자 조언이 아닙니다. 종목 선정 기준과 점수는
          특정 투자 전략을 기계적으로 구현한 것으로, 정확성이나 완전성을 보장하지 않습니다.
          투자 판단과 그에 따른 손익에 대한 책임은 전적으로 투자자 본인에게 있습니다.
        </AlertDescription>
      </Alert>
    </div>
  );
}
