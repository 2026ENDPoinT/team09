package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Display-only activity, deliberately excluded from the model conversation. */
final class AssistantActivityLog {
    private final JsonArray rows=new JsonArray();
    private final Set<Long> seen=new HashSet<>();
    private final Set<String> reported=new LinkedHashSet<>();
    synchronized JsonObject accept(JsonObject value){
        try {
            long id=value.get("id").getAsLong();String phase=value.get("phase").getAsString();
            String text=value.get("text").getAsString().strip();
            long at=value.get("timestampMs").getAsLong();
            if(id<=0||rows.size()>=200||!Set.of("plan","result","error").contains(phase)
                    ||at<0||text.isBlank()||text.length()>640||!seen.add(id))return null;
            JsonObject row=new JsonObject();row.addProperty("id",id);row.addProperty("phase",phase);
            row.addProperty("text",text);row.addProperty("timestampMs",at);
            rows.add(row);if(!phase.equals("plan"))reported.add(text);return row.deepCopy();
        }catch(RuntimeException malformed){return null;}
    }
    synchronized JsonArray snapshot(){return rows.deepCopy();}
    /** Suppress only an already-visible leading outcome, preserving every new detail. */
    synchronized String remainingAnswer(String answer,boolean streaming){
        String remaining=answer;
        while(!remaining.isBlank()){
            int newline=remaining.indexOf('\n');
            String rawFirst=newline<0?remaining:remaining.substring(0,newline);
            if(rawFirst.startsWith("    ")||rawFirst.startsWith("\t"))break;
            String first=rawFirst.strip();
            if(reported.contains(first)){
                remaining=newline<0?"":remaining.substring(newline+1).replaceFirst("^(?:[\\t ]*\\r?\\n)+","");continue;
            }
            // Do not briefly replay the duplicate while its first line is still arriving.
            if(streaming&&newline<0&&reported.stream().anyMatch(line->line.startsWith(first)))return "";
            break;
        }
        return remaining;
    }
    static JsonArray fromTurn(JsonObject turn){
        AssistantActivityLog log=new AssistantActivityLog();
        if(turn.has("activity")&&turn.get("activity").isJsonArray())
            for(JsonElement row:turn.getAsJsonArray("activity"))if(row.isJsonObject())log.accept(row.getAsJsonObject());
        return log.snapshot();
    }
}
