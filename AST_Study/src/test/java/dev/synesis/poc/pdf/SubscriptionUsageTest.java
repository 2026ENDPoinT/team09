package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.math.BigDecimal;
import java.time.Instant;

/** Average and usage dialog share the same paid generation counts, periods and credits. */
public final class SubscriptionUsageTest {
    private static void check(boolean condition,String label) {if(!condition)throw new AssertionError(label);}
    private static void equal(BigDecimal actual,String expected,String label) {
        check(actual.compareTo(new BigDecimal(expected))==0,label+": "+actual);
    }
    private static JsonObject wallet() {
        JsonObject wallet=new JsonObject();wallet.add("creditOperations",new JsonObject());wallet.add("creditHolds",new JsonObject());return wallet;
    }
    private static void operation(JsonObject wallet,String id,String category,Instant at,String credits) {
        JsonObject operation=new JsonObject();operation.addProperty("category",category);
        operation.addProperty("createdAtMs",at.toEpochMilli());operation.addProperty("credits",new BigDecimal(credits));
        operation.addProperty("unknownRequests",0);operation.addProperty("durationMs",60_000);
        wallet.getAsJsonObject("creditOperations").add(id,operation);
    }
    public static void main(String[] args) {
        Instant period=Instant.parse("2026-10-14T12:45:00Z"),paid=period.plusSeconds(300);
        JsonObject wallet=wallet();wallet.addProperty("planPurchasedAt",paid.toString());
        operation(wallet,"before-plan","summary",paid.minusMillis(1),"900");
        operation(wallet,"first-partial","summary",paid,"10");
        operation(wallet,"regenerated-after-deletion","summary",paid.plusMillis(1),"20");
        // No result files, completion flags or unique-PDF deduplication: paid attempts are the basis.
        wallet.getAsJsonObject("creditOperations").getAsJsonObject("first-partial").addProperty("processingComplete",false);
        for(String id:new String[]{"first-partial","regenerated-after-deletion"})
            wallet.getAsJsonObject("creditOperations").getAsJsonObject(id).addProperty("documentId","same-deleted-pdf");
        operation(wallet,"chat","chat",paid,"100");operation(wallet,"recording","voice",paid,"500");
        operation(wallet,"image-analysis","analysis",paid,"999");
        operation(wallet,"old-quiz","quiz",paid.minusMillis(1),"900");
        operation(wallet,"quiz-plan-and-generation","quiz",paid,"12.5");
        operation(wallet,"partial-quiz","quiz",paid.plusMillis(1),"2.5");
        wallet.getAsJsonObject("creditOperations").getAsJsonObject("partial-quiz").addProperty("unknownRequests",1);
        JsonObject hold=new JsonObject();hold.addProperty("credits",7);wallet.getAsJsonObject("creditHolds").add("pending",hold);
        var usage=SubscriptionUsage.fromWallet(wallet,period);
        check(usage.since().equals(paid),"same subscription period");check(usage.summaryCount()==2,"partial and regeneration counted");
        equal(usage.summaryCredits(),"30","summary total excludes chat, voice, analysis and holds");
        check(usage.quizCount()==2,"quiz attempts use subscription period and retain partial generation");
        equal(usage.quizCredits(),"15","quiz costs are aggregated once per operation");
        equal(usage.analysisCredits(),"999","quiz costs are excluded from analysis");
        check(usage.unknownRequests()==1,"quiz unknown usage is retained separately");
        equal(usage.averagePdfCredits(),"15","total divided by attempts");equal(usage.averagePdfKrw(),"34.5","2.3 won cost basis");
        check(SubscriptionUsage.report(usage).contains("AI 요약/개념 생성</h3>2회 · 30.00 크레딧"),"dialog uses same totals");
        check(SubscriptionUsage.report(usage).contains("문제집 생성</h3>2회 · 15.00 크레딧"),"dialog shows dedicated quiz credits");
        check(SubscriptionUsage.report(usage).contains("이미지·비교 분석: 999.00 크레딧"),"analysis display excludes quiz");
        check(SubscriptionUsage.report(usage).contains("저장된 문제집 열기·풀이는 차감하지 않아요"),"saved workbook cost policy is clear");
        String average=PdfLibraryPanel.pdfAverageHtml(usage);
        check(average.contains("34.50원") && average.contains("2회 생성 평균"),"profile displays same average");
        var empty=SubscriptionUsage.fromWallet(wallet,paid.plusSeconds(60));
        check(empty.summaryCount()==0,"reset cutoff");equal(empty.averagePdfCredits(),"0","empty average");equal(empty.averagePdfKrw(),"0","empty cost");
        check(empty.quizCount()==0,"quiz reset cutoff");equal(empty.quizCredits(),"0","quiz reset excludes old usage");
        check(PdfLibraryPanel.pdfAverageHtml(empty).contains("0.00원"),"zero rendered without NaN");
        JsonObject rounded=wallet();
        operation(rounded,"one","summary",paid,"3.33");operation(rounded,"two","summary",paid,"3.33");operation(rounded,"three","summary",paid,"3.34");
        var thirds=SubscriptionUsage.fromWallet(rounded,period);
        check(PdfLibraryPanel.pdfAverageHtml(thirds).contains("7.67원"),"round only after conversion to won");
        check(CreditWallet.display(thirds.averagePdfCredits()).equals("3.33"),"two decimal display");
        System.out.println("SubscriptionUsageTest OK: shared totals, partial/regeneration/deletion, periods, exclusions, zero and rounding.");
    }
}
