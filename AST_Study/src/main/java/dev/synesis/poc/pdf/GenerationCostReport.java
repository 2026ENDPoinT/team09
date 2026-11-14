package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.util.Locale;

/** Compact presentation only; persisted usage and statistics are unchanged. */
final class GenerationCostReport {
    private GenerationCostReport() { }

    static String html(JsonObject result, JsonObject request) {
        JsonObject usage = object(result, "runUsage");
        if (usage == null || !usage.has("usageBasedUsd"))
            return "<html>이번 생성 작업의 비용 기록을 확인하지 못했어요.</html>";
        JsonObject planning = object(request, "planningRunUsage");
        boolean customerView=k120(result);
        double group = chargedCost(planning,customerView);
        double generation = chargedCost(usage,customerView);
        double total = group + generation;
        double serviceCost=customerView ? number(planning,"synesisCoveredUsd")+number(usage,"synesisCoveredUsd") : 0;
        int unknown = (int)(number(planning, "unknownUsageRequests") + number(usage, "unknownUsageRequests"));
        boolean partial = result.has("processingComplete") && !result.get("processingComplete").getAsBoolean();
        JsonObject pending = object(result, "pendingOriginalUsage");
        int unresolved = (int)number(pending, "requests");
        StringBuilder body = new StringBuilder("<html><body style='width:360px;color:#182234'>");
        heading(body, partial || unknown > 0 || unresolved > 0 ? "확인된 이번 비용" : "총 비용");
        body.append("<span style='font-size:18pt'><b>").append(won(total))
            .append("</b></span> &nbsp;·&nbsp; ")
            .append(CreditWallet.display(CreditWallet.credits(total))).append(" 크레딧<br>");
        if(serviceCost>0) {
            double providerCost=providerCost(planning)+providerCost(usage);
            body.append("<small>실제 API 원가 ").append(won(providerCost)).append(" 중 ")
                .append(won(serviceCost)).append("은 시네시스가 부담했어요. 위 금액은 사용자 차감액이에요.</small><br>");
        }
        if (unknown > 0) {
            body.append("<small>사용량 미확인 ").append(unknown).append("건");
            double reserved = number(planning, "uncertainReservedUsd") + number(usage, "uncertainReservedUsd");
            if (reserved > 0) body.append(" · 내부 원가 확인 전 예산 ").append(won(reserved));
            body.append(" · 시네시스 부담, 사용자 추가 차감 없음");
            body.append("</small><br>");
        } else if (!partial && unresolved == 0 && number(planning, "requests") == 0 && number(usage, "requests") == 0) {
            body.append("<small>저장 결과를 재사용해 새 비용이 들지 않았어요.</small><br>");
        }
        if (partial) body.append("<small>생성이 아직 완료되지 않았어요. 완료된 설명은 보관했어요.</small><br>");
        if (unresolved > 0) body.append("<small>이 자료의 미확정 요청 ").append(unresolved)
            .append("건 · 내부 원가 확인 전 예산 ").append(won(number(pending,"reservedUsd")))
            .append(" (이전 실행 포함, 시네시스 부담·사용자 추가 차감 없음)</small><br>");
        if(partial && result.has("failedUnits") && result.get("failedUnits").isJsonArray()) {
            var reasons=new java.util.LinkedHashSet<String>();
            for(var value:result.getAsJsonArray("failedUnits"))if(value.isJsonObject()) {
                String detail=k120(result) ? failureDetail(value.getAsJsonObject()) : text(value.getAsJsonObject(),"detail");
                if(!detail.isBlank())reasons.add(detail);
            }
            if(k120(result)) {
                JsonObject metrics=object(result,"metrics");
                if(metrics!=null && metrics.has("unitTimings") && metrics.get("unitTimings").isJsonArray())
                    for(var value:metrics.getAsJsonArray("unitTimings"))if(value.isJsonObject()) {
                        String detail=text(value.getAsJsonObject(),"failureReason");
                        if(!detail.isBlank())reasons.add(detail);
                    }
            }
            if(!reasons.isEmpty()) {
                heading(body,"미완료 원인");
                for(String reason:reasons)body.append("<small>").append(escape(reason)).append("</small><br>");
            }
        }
        sourceReview(body,result);

        heading(body, "단계별 비용");
        body.append("<table width='100%' cellspacing='0' cellpadding='0'>");
        stage(body, "묶음 판단", "PDF 조각을 의미 단위로 묶어요.", planning == null ? "기록 없음" : won(group));
        stage(body, "강의 해설·개념 정리 생성", "묶인 단위의 강의 해설·개념 정리와 전체 흐름을 만들어요.", won(generation));
        body.append("</table>");
        unitTimings(body,result);

        heading(body, "예상 대비 차이");
        if (request == null || !request.has("approvedEstimateUsd")) {
            body.append("이번 실행의 예상 비용 기록이 없어요.<br>");
        } else {
            // The estimate was made after grouping. Include its settled cost
            // on both sides, so the expected and actual totals share a scope.
            double expected = number(request, "approvedEstimateUsd") + group;
            body.append("예상 ").append(won(expected)).append(" → ")
                .append(unknown > 0 ? "확인된 비용 " : "실제 ").append(won(total)).append("<br>");
            if (partial || unknown > 0 || unresolved > 0) body.append("생성 완료와 최종 비용 확인 후 차이를 비교할 수 있어요.<br>");
            else difference(body, "예상보다", total - expected, expected, false);
        }

        heading(body, "페이지당 단가");
        int pages = PdfGenerationCostStats.pages(result);
        if (pages == 0) {
            body.append("분석 페이지 수를 확인하지 못했어요.<br>");
        } else {
            if (partial) body.append("생성 완료 후 이번 페이지당 단가를 계산할 수 있어요.<br>");
            else body.append(unknown > 0 || unresolved > 0 ? "이번 확인 단가 " : "이번 ")
                .append(perPage(total / pages)).append(" · ").append(pages).append("쪽 기준<br>");
            JsonObject comparison = object(result, "pageCostComparison");
            JsonObject overall = object(comparison, "overallTotal");
            if (comparison == null || comparison.has("historyUnavailable")) {
                body.append("전체 평균 기록을 확인하지 못했어요.<br>");
            } else if (overall == null || number(overall, "pages") <= 0) {
                body.append("전체 평균: 집계할 기록이 아직 없어요.<br>");
            } else {
                body.append(serviceCost>0?"전체 평균 API 원가 ":"전체 평균 ").append(perPage(number(overall, "usdPerPage")))
                    .append(" · 총비용 확인 ").append((long)number(overall, "runs")).append("건<br>");
                JsonObject previous = object(comparison, "previousTotal");
                boolean eligible = comparison.has("currentEligible") && comparison.get("currentEligible").getAsBoolean();
                if (serviceCost==0 && !partial && unresolved == 0 && unknown == 0 && eligible && previous != null && number(previous, "pages") > 0) {
                    double baseline = number(previous, "usdPerPage");
                    difference(body, "이전 평균보다", total / pages - baseline, baseline, true);
                }
            }
        }
        return body.append("</body></html>").toString();
    }

    private static void heading(StringBuilder body, String label) {
        body.append("<h3 style='margin-top:14px;margin-bottom:6px'>").append(label).append("</h3>");
    }

    private static void sourceReview(StringBuilder body,JsonObject result) {
        if(!k120(result) && !"newest-k1-1-3".equals(text(result,"strategy")))return;
        boolean reviewNeeded="needs_review".equals(text(result,"reviewStatus"));
        if(k120(result)) {
            reviewNeeded=false;
            if(result.has("coverage") && result.get("coverage").isJsonArray())
                for(var value:result.getAsJsonArray("coverage"))if(value.isJsonObject()
                        && "needs_review".equals(text(value.getAsJsonObject(),"state"))) {reviewNeeded=true;break;}
        }
        if(reviewNeeded) {
            heading(body,"원문 반영 확인");
            body.append("생성된 설명에 아직 원문 확인이 필요한 부분이 있어요. 다시 생성하면 해당 단락을 보완해요.<br>");
        }
        if(!result.has("sourceNotes") || !result.get("sourceNotes").isJsonArray())return;
        var notes=new java.util.LinkedHashSet<String>();
        for(var value:result.getAsJsonArray("sourceNotes"))if(value.isJsonObject()) {
            JsonObject row=value.getAsJsonObject(),note=object(row,"sourceNote");
            if(note==null)continue;
            String reason=text(note,"reason");
            if(!reason.isBlank())notes.add("p."+(int)number(row,"page")+" · "+reason);
        }
        if(notes.isEmpty())return;
        heading(body,"원문 참고사항");
        for(String note:notes)body.append("<small>").append(escape(note)).append("</small><br>");
    }

    private static void unitTimings(StringBuilder body,JsonObject result) {
        if(result.has("cacheHit") && result.get("cacheHit").getAsBoolean())return;
        JsonObject metrics=object(result,"metrics");
        if(metrics==null || !metrics.has("unitTimings") || !metrics.get("unitTimings").isJsonArray())return;
        if(k120(result)) { separatedUnitTimings(body,metrics);return; }
        heading(body,"단위별 처리 시간");
        body.append("<small>이번 실행의 API 요청·대기 시간이에요. 함께 요청한 단위는 같은 시간을 표시해요.<br>")
            .append("병렬 처리하므로 아래 시간을 더한 값은 총 처리 시간과 달라요.</small><br>")
            .append("<table width='100%' cellspacing='0' cellpadding='3'>");
        for(var value:metrics.getAsJsonArray("unitTimings")) {
            if(!value.isJsonObject())continue;
            JsonObject row=value.getAsJsonObject();String status=text(row,"status");
            String state=switch(status) {
                case "completed" -> "완료";case "reused" -> "저장 결과 재사용";
                case "local" -> "로컬 분류 완료";
                case "failed" -> "미완료";default -> "대기";
            };
            String duration=row.has("requestSeconds") && Double.isFinite(number(row,"requestSeconds"))
                ? PdfWorkspace.formatElapsed((long)(Math.max(0,number(row,"requestSeconds"))*1_000_000_000L))
                : status.equals("reused") || status.equals("local") ? "새 요청 없음" : "기록 없음";
            body.append("<tr><td valign='top'><b>").append((int)number(row,"index")).append(". ")
                .append(escape(text(row,"title"))).append("</b><br><small>");
            if(row.has("pages") && row.get("pages").isJsonArray()) {
                var pages=row.getAsJsonArray("pages");
                for(int i=0;i<pages.size();i++) {
                    if(i>0)body.append(", ");body.append("p.").append(escape(pages.get(i).getAsString()));
                }
            }
            body.append(" · ").append(state);
            if(row.has("sharedRequest") && row.get("sharedRequest").getAsBoolean())body.append(" · 묶음 요청 시간");
            body.append("</small></td><td align='right' valign='top'>").append(duration).append("</td></tr>");
        }
        body.append("</table>");
    }

    private static boolean k120(JsonObject result) {return java.util.Set.of("newest-k1-2-0","newest-k1-2-1","newest-k1-2-2","newest-k1-2-3","newest-k1-2-4","newest-k1-2-5").contains(text(result,"strategy"));}

    private static double chargedCost(JsonObject usage,boolean customerView) {
        return customerView && usage!=null && measured(usage,"customerChargeUsd")
            ? number(usage,"customerChargeUsd") : number(usage,"usageBasedUsd");
    }

    private static double providerCost(JsonObject usage) {
        return usage!=null && measured(usage,"providerUsageUsd")
            ? number(usage,"providerUsageUsd") : number(usage,"usageBasedUsd");
    }

    private static boolean measured(JsonObject value,String key) {
        try{return value.has(key) && value.get(key).isJsonPrimitive()
            && value.getAsJsonPrimitive(key).isNumber() && Double.isFinite(value.get(key).getAsDouble());}
        catch(RuntimeException invalid){return false;}
    }

    private static String elapsed(JsonObject row,String key) {
        return PdfWorkspace.formatElapsed((long)(Math.max(0,number(row,key))*1_000_000_000L));
    }

    private static void separatedUnitTimings(StringBuilder body,JsonObject metrics) {
        heading(body,"단위별 처리 시간");
        body.append("<small>비용 확보를 기다린 시간과 실제 API 요청 시간을 구분해요.<br>")
            .append("병렬 처리하므로 아래 시간을 더한 값은 총 처리 시간과 달라요.</small><br>")
            .append("<table width='100%' cellspacing='0' cellpadding='3'>");
        for(var value:metrics.getAsJsonArray("unitTimings")) {
            if(!value.isJsonObject())continue;
            JsonObject row=value.getAsJsonObject();String status=text(row,"status");
            String state=switch(status) {
                case "completed" -> "완료";case "reused" -> "저장 결과 재사용";
                case "local" -> "로컬 분류 완료";case "failed" -> "미완료";default -> "대기";
            };
            body.append("<tr><td><b>").append((int)number(row,"index")).append(". ")
                .append(escape(text(row,"title"))).append("</b><br><small>");
            if(row.has("pages") && row.get("pages").isJsonArray()) {
                var pages=row.getAsJsonArray("pages");
                for(int i=0;i<pages.size();i++) {
                    if(i>0)body.append(", ");body.append("p.").append(escape(pages.get(i).getAsString()));
                }
            }
            body.append(" · ").append(state).append("<br>");
            if(status.equals("reused") || status.equals("local"))body.append("새 요청 없음");
            else {
                String total=measured(row,"totalSeconds") ? "totalSeconds" : "requestSeconds";
                body.append(measured(row,total) ? "총 "+elapsed(row,total) : "시간 기록 없음");
                if(measured(row,"reservationWaitSeconds") && number(row,"reservationWaitSeconds")>0)
                    body.append(" · 비용 대기 ").append(elapsed(row,"reservationWaitSeconds"));
                if(measured(row,"localQueueSeconds") && number(row,"localQueueSeconds")>0)
                    body.append(" · 호출 대기 ").append(elapsed(row,"localQueueSeconds"));
                if(measured(row,"apiSeconds"))body.append(number(row,"apiSeconds")>0
                    ? " · API 요청 "+elapsed(row,"apiSeconds") : " · 요청 미전송");
            }
            String failure=failureDetail(row);
            if(status.equals("failed") && !failure.isBlank())body.append("<br>").append(escape(failure));
            body.append("</small></td></tr>");
        }
        body.append("</table>");
    }

    private static String failureDetail(JsonObject row) {
        String reason=text(row,"detail");
        if(reason.isBlank())reason=text(row,"failureReason");
        if(!reason.isBlank())return reason;
        return switch(text(row,"error")) {
            case "InsufficientCredits", "CreditExceeded" -> "사용 가능한 생성 비용이 부족해 남은 요청을 보내지 못했어요.";
            case "BudgetExceeded", "BudgetExceededError" -> "설정된 생성 비용 한도에 도달했어요.";
            case "TimeoutError" -> "요청이 제한 시간 안에 완료되지 않았어요.";
            default -> "";
        };
    }

    private static String text(JsonObject value,String key) {
        return value.has(key) && value.get(key).isJsonPrimitive() ? value.get(key).getAsString() : "";
    }
    private static String escape(String value) {
        return value.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\"","&quot;");
    }

    private static void stage(StringBuilder body, String label, String description, String amount) {
        body.append("<tr><td style='padding-bottom:8px'><b>").append(label)
            .append("</b><br><small style='color:#65758d'>").append(description)
            .append("</small></td><td align='right' valign='top'>").append(amount).append("</td></tr>");
    }

    private static void difference(StringBuilder body, String label, double delta, double baseline, boolean perPage) {
        int decimals = perPage ? 3 : 2;
        if (Math.abs(delta * 1400) < .5 * Math.pow(10, -decimals)) {
            body.append(label.equals("예상보다") ? "예상과 같아요.<br>" : "이전 평균과 같아요.<br>");
            return;
        }
        body.append(label).append(" ").append(perPage ? perPage(Math.abs(delta)) : won(Math.abs(delta)))
            .append(delta > 0 ? " 높아요" : " 낮아요");
        if (baseline > 0) body.append(String.format(Locale.ROOT, " (%.1f%%)", Math.abs(delta) / baseline * 100));
        body.append(".<br>");
    }

    private static String won(double usd) { return String.format(Locale.ROOT, "%,.2f원", usd * 1400); }
    private static String perPage(double usd) { return String.format(Locale.ROOT, "%,.3f원/쪽", usd * 1400); }
    private static JsonObject object(JsonObject value, String key) { return PdfGenerationCostStats.object(value, key); }
    private static double number(JsonObject value, String key) {
        try { return value != null && value.has(key) ? value.get(key).getAsDouble() : 0; }
        catch (RuntimeException invalid) { return 0; }
    }
}
