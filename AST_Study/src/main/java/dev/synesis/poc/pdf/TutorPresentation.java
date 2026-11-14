package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.time.*;
import java.time.format.DateTimeFormatter;

/** Pure presentation rules; no model call or conversation-memory changes. */
final class TutorPresentation {
    private static final java.util.regex.Pattern TUTOR_OFFER_ENDING=java.util.regex.Pattern.compile(
        "(?:(?:해|알려|보여|풀어|도와)\\s*(?:줄|드릴)|(?:살펴|알아|해)\\s*볼)까(?:요)?[?？.!。~\\s]*$");
    private TutorPresentation() {}
    static String relativeTime(long timestamp,long now){
        long elapsed=Math.max(0,now-timestamp);
        if(elapsed<=2*60_000L)return "방금";
        if(elapsed<=58*60_000L)return elapsed/60_000+"분 전";
        if(elapsed<=23*3_600_000L)return Math.max(1,elapsed/3_600_000)+"시간 전";
        if(elapsed>14*86_400_000L)return "오래 전";
        return Math.max(1,elapsed/86_400_000)+"일 전";
    }
    static String timeLabel(long timestamp,long now){
        return DateTimeFormatter.ofPattern("MM/dd HH:mm").withZone(ZoneId.of("Asia/Seoul"))
            .format(Instant.ofEpochMilli(timestamp))+"  "+relativeTime(timestamp,now);
    }
    static String followUp(JsonObject value){
        if(value!=null){
            for(String flag:new String[]{"blocked","notFound","needsClarification","evidenceIncomplete","needsExternalSearch"})
                if(value.has(flag)&&value.get(flag).isJsonPrimitive()&&value.get(flag).getAsBoolean())return "";
            if(value.has("kind")&&value.get("kind").isJsonPrimitive()
                &&java.util.Set.of("blocked","greeting","social","error","no_evidence").contains(value.get("kind").getAsString()))return "";
        }
        if(value==null||!value.has("followUpQuestion")||!value.get("followUpQuestion").isJsonPrimitive()
            ||!value.get("followUpQuestion").getAsJsonPrimitive().isString())return "";
        String question=value.get("followUpQuestion").getAsString().strip();
        if(question.isEmpty()||question.codePointCount(0,question.length())>160
            ||question.codePoints().anyMatch(c->Character.isISOControl(c)||c==0x2028||c==0x2029)||question.contains("```"))return "";
        if(TUTOR_OFFER_ENDING.matcher(question).find())return "";
        return question;
    }
}
