package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** Persistent feature usage survives document deletion; billing is shared with Python. */
public final class SubscriptionUsage {
    private SubscriptionUsage() {}
    public static void recoverReservations() throws IOException {
        CreditWallet.recoverReservations(PdfLibraryStore.defaultRoot());
    }
    static void activate(Path root) throws IOException {
        var totals=PdfUsageStore.read(root,PdfLibraryStore.list(root),ProfileUsagePeriod.since(root));
        if(totals.unreadableFiles()>0)throw new IOException("사용량 기록을 모두 읽지 못해 유료 호출을 중단했어요.");
        CreditWallet.activateBilling(root,totals.usd());
    }
    static JsonObject legacyOperations(Path root) throws IOException {
        JsonObject operations=new JsonObject();List<Path> ledgers=new ArrayList<>();
        if(Files.isDirectory(root))try(var files=Files.walk(root,7)) {
            files.filter(p->p.getParent()!=null && p.getParent().getFileName().toString().equals("usage") && p.toString().endsWith(".json")).forEach(ledgers::add);
        }
        Path history=dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("pdf-usage-history");
        if(Files.isDirectory(history))try(var files=Files.list(history)) {files.filter(p->p.toString().endsWith(".json")).forEach(ledgers::add);}
        for(Path file:ledgers) {
            JsonObject ledger=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
            if(!ledger.has("operationId") || !ledger.has("requests"))continue;
            String id=ledger.get("operationId").getAsString();if(operations.has(id))continue;
            BigDecimal usd=BigDecimal.ZERO;int unknown=0;boolean summary=false;
            for(JsonElement element:ledger.getAsJsonArray("requests")) {
                JsonObject request=element.getAsJsonObject();String kind=request.has("kind")?request.get("kind").getAsString():"";
                summary|=kind.startsWith("region_") || kind.startsWith("page_") || kind.startsWith("semantic_") || kind.equals("summary_reduce");
                if(request.has("state") && request.get("state").getAsString().equals("settled"))
                    usd=usd.add(request.has("estimatedUsd")?request.get("estimatedUsd").getAsBigDecimal():BigDecimal.ZERO);
                else unknown++;
            }
            if(ledger.getAsJsonArray("requests").isEmpty())continue;
            JsonObject operation=new JsonObject();
            operation.addProperty("category",ledger.has("category")?ledger.get("category").getAsString():summary?"summary":"chat");
            operation.addProperty("createdAtMs",ledger.has("createdAtMs")?ledger.get("createdAtMs").getAsLong():Files.readAttributes(file,java.nio.file.attribute.BasicFileAttributes.class).creationTime().toMillis());
            operation.addProperty("credits",usd.multiply(CreditWallet.CREDITS_PER_USD));operation.addProperty("unknownRequests",unknown);
            operations.add(id,operation);
        }
        return operations;
    }
    record Snapshot(Instant since,int summaryCount,BigDecimal summaryCredits,int chatCount,BigDecimal chatCredits,
                    int quizCount,BigDecimal quizCredits,
                    BigDecimal analysisCredits,int unknownRequests,BigDecimal heldCredits) {
        BigDecimal averagePdfCredits() {
            return summaryCount==0?BigDecimal.ZERO:summaryCredits.divide(BigDecimal.valueOf(summaryCount),20,java.math.RoundingMode.HALF_UP);
        }
        BigDecimal averagePdfKrw() {return averagePdfCredits().multiply(CreditWallet.COST_KRW_PER_CREDIT);}
    }

    static Snapshot read(Path root) throws IOException {
        activate(root);
        return fromWallet(CreditWallet.usageData(root),ProfileUsagePeriod.since(root));
    }

    static Snapshot fromWallet(JsonObject wallet,Instant since) {
        if(wallet.has("planPurchasedAt")) {
            Instant paid=Instant.parse(wallet.get("planPurchasedAt").getAsString());if(paid.isAfter(since))since=paid;
        }
        int summary=0,chat=0,quiz=0,unknown=0;
        BigDecimal summaryCredits=BigDecimal.ZERO,chatCredits=BigDecimal.ZERO,quizCredits=BigDecimal.ZERO,
            analysisCredits=BigDecimal.ZERO;
        for(var entry:wallet.getAsJsonObject("creditOperations").entrySet()) {
            JsonObject operation=entry.getValue().getAsJsonObject();
            if(operation.get("createdAtMs").getAsLong()<since.toEpochMilli())continue;
            BigDecimal credits=operation.get("credits").getAsBigDecimal();
            unknown+=operation.has("unknownRequests")?operation.get("unknownRequests").getAsInt():0;
            switch(operation.get("category").getAsString()) {
                case "summary" -> {summary++;summaryCredits=summaryCredits.add(credits);}
                case "chat" -> {chat++;chatCredits=chatCredits.add(credits);}
                case "quiz" -> {quiz++;quizCredits=quizCredits.add(credits);}
                case "voice" -> { /* Legacy wallet entries still count toward the saved balance. */ }
                default -> analysisCredits=analysisCredits.add(credits);
            }
        }
        BigDecimal held=BigDecimal.ZERO;
        for(var hold:wallet.getAsJsonObject("creditHolds").entrySet())held=held.add(hold.getValue().getAsJsonObject().get("credits").getAsBigDecimal());
        return new Snapshot(since,summary,summaryCredits,chat,chatCredits,quiz,quizCredits,analysisCredits,unknown,held);
    }

    static String report(Path root) throws IOException {return report(read(root));}

    static String report(Snapshot usage) {
        Instant since=usage.since();
        int summary=usage.summaryCount(),chat=usage.chatCount(),quiz=usage.quizCount(),unknown=usage.unknownRequests();
        BigDecimal summaryCredits=usage.summaryCredits(),chatCredits=usage.chatCredits(),quizCredits=usage.quizCredits(),
            analysisCredits=usage.analysisCredits(),held=usage.heldCredits();
        String date=DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm:ss").withZone(ZoneId.of("Asia/Seoul")).format(since);
        String html="<html><body style='width:440px;color:#182234'><h2>내 구독 사용량</h2><p>"+date+" 이후 · 현재 플랜 결제일 또는 초기화 시각 기준</p>"
            +"<h3>AI 요약/개념 생성</h3>"+summary+"회 · "+CreditWallet.display(summaryCredits)+" 크레딧"
            +"<h3>AI 채팅</h3>"+chat+"회 · "+CreditWallet.display(chatCredits)+" 크레딧"
            +"<h3>문제집 생성</h3>"+quiz+"회 · "+CreditWallet.display(quizCredits)+" 크레딧"
            +"<p><small>요약은 유료 API 요청이 발생한 생성 작업 기준이며, 저장 결과 재사용은 제외해요.<br>채팅은 무료·캐시 답변도 횟수에 포함하고 실제 발생한 비용만 차감해요.<br>문제집 생성은 출제 배분·문제 생성의 실제 비용을 모두 포함해요. 저장된 문제집 열기·풀이는 차감하지 않아요.<br>PDF를 삭제해도 사용 기록은 유지해요.</small></p>";
        if(analysisCredits.signum()>0)html+="<p>이미지·비교 분석: "+CreditWallet.display(analysisCredits)+" 크레딧</p>";
        if(unknown>0)html+="<p>사용량 미확인 API 요청 "+unknown+"건 · 시네시스 부담<br>나중에 비용이 확인돼도 사용자 크레딧은 추가 차감하지 않아요.</p>";
        if(held.signum()>0)html+="<p>진행 중인 호출의 임시 예약: "+CreditWallet.display(held)+" 크레딧</p>";
        return html+"</body></html>";
    }
}
