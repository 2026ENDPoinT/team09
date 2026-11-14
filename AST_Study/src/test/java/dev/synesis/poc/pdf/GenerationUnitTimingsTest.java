package dev.synesis.poc.pdf;

import com.google.gson.JsonParser;

public final class GenerationUnitTimingsTest {
    public static void main(String[] args) {
        var result=JsonParser.parseString("""
            {"runUsage":{"usageBasedUsd":0},"processingComplete":false,
             "metrics":{"unitTimings":[
                {"index":1,"title":"포인터 <T> & 배열","pages":[28,29],"status":"failed","requestSeconds":60.603,"sharedRequest":true},
                {"index":2,"title":"재사용","pages":[2],"status":"reused"},
                {"index":3,"title":"미측정","pages":[3],"status":"pending"}]}}
            """).getAsJsonObject();
        String html=GenerationCostReport.html(result,null);
        for(String required:new String[]{"단위별 처리 시간","1분 0초","묶음 요청 시간","p.28, p.29",
                "포인터 &lt;T&gt; &amp; 배열","미완료","새 요청 없음","기록 없음"})
            if(!html.contains(required))throw new AssertionError(required+" missing: "+html);
        result.addProperty("cacheHit",true);
        if(GenerationCostReport.html(result,null).contains("단위별 처리 시간"))
            throw new AssertionError("Old run times must not appear as this cache hit's times");
        System.out.println("GenerationUnitTimingsTest passed");
    }
}
