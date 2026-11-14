package dev.synesis.poc.pdf;

import com.google.gson.JsonParser;

/** Customer charges and provider expense must not be displayed interchangeably. */
public final class GenerationK120CustomerCostTest {
    public static void main(String[] args) {
        var result=JsonParser.parseString("""
            {"strategy":"newest-k1-2-0","processingComplete":true,"sourcePages":[1],
             "runUsage":{"usageBasedUsd":0.05,"providerUsageUsd":0.05,
                         "customerChargeUsd":0.02,"synesisCoveredUsd":0.03,"requests":1},
             "pageCostComparison":{"currentEligible":true,"overallTotal":{"pages":2,"runs":2,"usdPerPage":0.05},
                                   "previousTotal":{"pages":1,"usdPerPage":0.05}}}
            """).getAsJsonObject();
        var request=JsonParser.parseString("""
            {"planningRunUsage":{"usageBasedUsd":0.01,"providerUsageUsd":0.01,
                                 "customerChargeUsd":0.004,"synesisCoveredUsd":0.006,"requests":1}}
            """).getAsJsonObject();
        String html=GenerationCostReport.html(result,request);
        for(String required:new String[]{"<b>33.60원</b>","실제 API 원가 84.00원 중 50.40원은 시네시스가 부담",
                "위 금액은 사용자 차감액","5.60원","28.00원","전체 평균 API 원가"})
            if(!html.contains(required))throw new AssertionError(required+" missing: "+html);
        if(html.contains("이전 평균보다"))throw new AssertionError("Customer charge compared against provider expense");
        result.getAsJsonObject("runUsage").addProperty("customerChargeUsd",0);
        request.getAsJsonObject("planningRunUsage").addProperty("customerChargeUsd",0);
        if(!GenerationCostReport.html(result,request).contains("<b>0.00원</b>"))
            throw new AssertionError("A confirmed zero customer charge fell back to provider expense");
        result.addProperty("strategy","newest-k1-1-3");
        html=GenerationCostReport.html(result,request);
        if(!html.contains("<b>84.00원</b>") || html.contains("위 금액은 사용자 차감액"))
            throw new AssertionError("Legacy charge presentation changed");
        System.out.println("GenerationK120CustomerCostTest passed");
    }
}
