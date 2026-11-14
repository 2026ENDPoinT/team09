package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;

public final class GenerationIncompleteCostReportTest {
    public static void main(String[] args) {
        JsonObject result=new JsonObject(),usage=new JsonObject(),pending=new JsonObject(),request=new JsonObject();
        usage.addProperty("usageBasedUsd",0);usage.addProperty("requests",0);
        result.add("runUsage",usage);result.addProperty("processingComplete",false);
        pending.addProperty("requests",10);pending.addProperty("reservedUsd",.2);
        result.add("pendingOriginalUsage",pending);request.addProperty("approvedEstimateUsd",.03);
        String html=GenerationCostReport.html(result,request);
        if(!html.contains("아직 완료되지") || !html.contains("미확정 요청 10건")
            || html.contains("저장 결과를 재사용") || html.contains("100.0%")
            || html.contains("예상보다"))throw new AssertionError(html);
        result.addProperty("processingComplete",true);result.remove("pendingOriginalUsage");
        if(!GenerationCostReport.html(result,request).contains("저장 결과를 재사용"))
            throw new AssertionError("Completed free cache reuse should remain visible");
        result.addProperty("strategy","newest-k1-1-3");result.addProperty("reviewStatus","needs_review");
        var notes=new com.google.gson.JsonArray();var row=new JsonObject();var note=new JsonObject();
        row.addProperty("page",118);note.addProperty("reason","보조 그림의 <차수> 표기가 없어요.");
        row.add("sourceNote",note);notes.add(row);result.add("sourceNotes",notes);
        html=GenerationCostReport.html(result,request);
        if(!html.contains("해당 단락을 보완") || !html.contains("원문 참고사항")
            || !html.contains("p.118") || !html.contains("&lt;차수&gt;"))throw new AssertionError(html);
        result.addProperty("reviewStatus","complete");
        html=GenerationCostReport.html(result,request);
        if(html.contains("아직 원문 확인") || !html.contains("원문 참고사항"))throw new AssertionError(html);
        result.addProperty("strategy","newest-k1-1-2");
        if(GenerationCostReport.html(result,request).contains("원문 참고사항"))
            throw new AssertionError("Older engine presentation changed");
        System.out.println("GenerationIncompleteCostReportTest passed");
    }
}
