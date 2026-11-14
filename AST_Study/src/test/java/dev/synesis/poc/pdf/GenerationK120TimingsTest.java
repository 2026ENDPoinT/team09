package dev.synesis.poc.pdf;

import com.google.gson.JsonParser;

/** No app/window: render the persisted time accounting and unsent failure. */
public final class GenerationK120TimingsTest {
    public static void main(String[] args) {
        var result=JsonParser.parseString("""
            {"strategy":"newest-k1-2-0","runUsage":{"usageBasedUsd":0.05},"processingComplete":false,
             "reviewStatus":"needs_review","coverage":[{"state":"pending_summary"}],
             "failedUnits":[{"unitId":"u2","error":"InsufficientCredits"}],
             "metrics":{"unitTimings":[
                {"index":1,"title":"여가와 <교류>","pages":[13],"status":"completed",
                 "totalSeconds":434,"reservationWaitSeconds":412,"apiSeconds":22,"localQueueSeconds":0},
                {"index":2,"title":"못 보낸 요청","pages":[14],"status":"failed",
                 "totalSeconds":450,"reservationWaitSeconds":450,"apiSeconds":0,"localQueueSeconds":0,
                 "failureReason":"생성 비용 <부족>"},
                {"index":3,"title":"이전 결과","pages":[15],"status":"reused"},
                {"index":4,"title":"아직 없는 기록","pages":[16],"status":"failed","apiSeconds":null}]}}
            """).getAsJsonObject();
        String html=GenerationCostReport.html(result,null);
        for(String required:new String[]{"미완료 원인","생성 비용이 부족해","총 7분 14초",
                "비용 대기 6분 52초","API 요청 22.0초","요청 미전송","생성 비용 &lt;부족&gt;",
                "여가와 &lt;교류&gt;","새 요청 없음","시간 기록 없음"})
            if(!html.contains(required))throw new AssertionError(required+" missing: "+html);
        if(html.contains("valign='top'>총"))throw new AssertionError("Time breakdown must not use the cramped right column");
        if(html.contains("생성된 설명에 아직 원문 확인"))throw new AssertionError("Unsent content is not a completed-content review failure");
        result.getAsJsonArray("coverage").get(0).getAsJsonObject().addProperty("state","needs_review");
        if(!GenerationCostReport.html(result,null).contains("생성된 설명에 아직 원문 확인"))
            throw new AssertionError("Actual review flags must remain visible");
        result.addProperty("strategy","newest-k1-1-3");
        html=GenerationCostReport.html(result,null);
        if(html.contains("비용 대기") || html.contains("요청 미전송"))
            throw new AssertionError("Older engine time presentation changed");
        result.addProperty("strategy","newest-k1-2-0");result.addProperty("cacheHit",true);
        if(GenerationCostReport.html(result,null).contains("단위별 처리 시간"))
            throw new AssertionError("Cached run must not show earlier timings as new");
        System.out.println("GenerationK120TimingsTest passed");
    }
}
