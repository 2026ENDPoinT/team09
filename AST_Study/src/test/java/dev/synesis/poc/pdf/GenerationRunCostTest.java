package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.concurrent.TimeUnit;

/** Offline completion cost presentation, accounting scope and uncertain usage. */
public final class GenerationRunCostTest {
    private static JsonObject usage(double usd,int requests) {
        JsonObject u=new JsonObject();u.addProperty("usageBasedUsd",usd);u.addProperty("requests",requests);return u;
    }
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private static int count(String text,String needle){return (text.length()-text.replace(needle,"").length())/needle.length();}
    public static void main(String[] args) {
        JsonObject result=new JsonObject();result.add("runUsage",usage(.11532568,46));
        JsonObject request=new JsonObject();request.add("planningRunUsage",usage(.0342032,18));
        request.addProperty("approvedEstimateUsd",.137739);request.addProperty("estimateLowUsd",.04);request.addProperty("estimateHighUsd",.22);
        String combined=PdfWorkspace.generationRunReportHtml(result,request);
        check(combined.contains("209.34원"),"Total must include grouping");
        check(combined.contains("47.88원") && combined.contains("161.46원"),"Both paid stages stay visible");
        check(combined.contains("240.72원") && combined.contains("예상보다 31.38원 낮아요 (13.0%)"),"Estimate and actual must use the same stage scope");
        check(!combined.contains("$") && !combined.contains("USD") && count(combined,"크레딧")==1,"Only won throughout; credits once alongside total");
        check(count(combined,"<h3 ")==4,"Exactly four compact cost sections");
        check(combined.indexOf("총 비용")<combined.indexOf("단계별 비용")
            && combined.indexOf("단계별 비용")<combined.indexOf("예상 대비 차이")
            && combined.indexOf("예상 대비 차이")<combined.indexOf("페이지당 단가"),"Requested section order");
        check(!combined.contains("예상 범위") && !combined.contains("estimateBasis") && !combined.contains("과거 기록 포함 생성 평균"),"Remove verbose historical and technical explanations");
        JsonObject detailed=result.deepCopy();JsonArray pages=new JsonArray();for(int p=1;p<=39;p++)pages.add(p);detailed.add("sourcePages",pages);
        JsonObject comparison=JsonParser.parseString("""
            {"currentEligible":true,"currentTotalUsd":0.14952888,"currentGenerationUsd":0.11532568,
             "missingPlanningRuns":69,"previousTotal":{"runs":2,"pages":80,"usdPerPage":0.002},
             "overallTotal":{"runs":3,"pages":119,"usdPerPage":0.0026},
             "overallGeneration":{"runs":90,"pages":2000,"usdPerPage":0.0001}}
            """).getAsJsonObject();
        detailed.add("pageCostComparison",comparison);
        String added=PdfWorkspace.generationRunReportHtml(detailed,request);
        check(added.contains("5.368원/쪽") && added.contains("39쪽 기준") && added.contains("전체 평균 3.640원/쪽")
            && added.contains("이전 평균보다 2.568원/쪽 높아요 (91.7%)"),"Keep total-inclusive current and weighted average page rates");
        check(!added.contains("0.140원/쪽") && !added.contains("69건"),"Do not mix generation-only legacy averages into total cost");
        request.add("planningRunUsage",usage(0,0));
        check(PdfWorkspace.generationRunReportHtml(result,request).contains("161.46원"),"Cached grouping is not billed again");
        result.add("runUsage",usage(0,0));request.add("planningRunUsage",usage(.01,1));
        String planningOnly=PdfWorkspace.generationRunReportHtml(result,request);
        check(planningOnly.contains("14.00원")&&!planningOnly.contains("새 비용이 들지 않았어요"),"Paid grouping is not free when generation is cached");
        JsonObject uncertain=usage(0,1);uncertain.addProperty("unknownUsageRequests",1);uncertain.addProperty("uncertainReservedUsd",.02);request.add("planningRunUsage",uncertain);
        String unknown=PdfWorkspace.generationRunReportHtml(result,request);
        check(unknown.contains("확인된 총 비용") && unknown.contains("사용량 미확인 1건") && unknown.contains("별도 예약액 28.00원")
            && unknown.contains("위 비용에 미포함") && !unknown.contains("예상보다"),"Unknown costs retain their reservation and defer final comparison");
        request.add("planningRunUsage",usage(0,0));
        check(PdfWorkspace.generationRunReportHtml(result,request).contains("새 비용이 들지 않았어요"),"Both cached stages are free");
        check(PdfWorkspace.generationRunReportHtml(result).contains("기록 없음"),"Missing grouping is not invented");
        JsonObject zeroEstimate=new JsonObject();zeroEstimate.addProperty("approvedEstimateUsd",0);zeroEstimate.add("planningRunUsage",usage(0,0));
        result.add("runUsage",usage(.01,1));
        String positive=PdfWorkspace.generationRunReportHtml(result,zeroEstimate);
        check(positive.contains("예상보다 14.00원 높아요") && !positive.contains("Infinity") && !positive.contains("NaN"),"Zero estimate must not divide by zero");
        result.add("runUsage",usage(0,0));
        check(PdfWorkspace.generationRunReportHtml(result,zeroEstimate).contains("예상과 같아요"),"Equal costs are not falsely higher or lower");
        check(PdfWorkspace.formatElapsed(TimeUnit.SECONDS.toNanos(44)).equals("44.0초")
            && PdfWorkspace.formatElapsed(TimeUnit.SECONDS.toNanos(65)).equals("1분 5초"),"Keep elapsed time readable");
        System.out.println("PASS: compact won-only costs, stages, estimate deltas, page rates, uncertainty and elapsed time");
    }
}
