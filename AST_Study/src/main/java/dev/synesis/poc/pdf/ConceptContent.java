package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Role-first presentation of saved entries; never rewrites a definition or condition. */
final class ConceptContent {
    record Row(String field,JsonObject entry,int entryIndex) {}

    static List<Row> rows(JsonArray entries,String... fields) {
        List<Row> rows=new ArrayList<>();
        for(String field:fields) {
            Map<String,Row> distinct=new LinkedHashMap<>();
            for(int index=0;index<entries.size();index++) {
                JsonObject entry=entries.get(index).getAsJsonObject();
                String text=entry.has(field) && !entry.get(field).isJsonNull()?entry.get(field).getAsString():"";
                if(text.isBlank())continue;
                // Only exact text is redundant. Numbers, conditions and TeX
                // remain significant; no fuzzy similarity or synonym merging.
                String key=text.strip();
                if(entry.has("slideLens") && !entry.get("slideLens").isJsonNull()
                    || entry.has("stepFlow") && !entry.get("stepFlow").isJsonNull())key+="\u0000"+index;
                Row previous=distinct.get(key);
                if(previous==null)distinct.put(key,new Row(field,entry.deepCopy(),index));
                else {
                    union(previous.entry(),entry,"evidence");
                    union(previous.entry(),entry,"visualPages");
                    if(entry.has("standardKnowledgeUsed") && entry.get("standardKnowledgeUsed").getAsBoolean())
                        previous.entry().addProperty("standardKnowledgeUsed",true);
                }
            }
            rows.addAll(distinct.values());
        }
        return rows;
    }

    private static void union(JsonObject target,JsonObject addition,String field) {
        JsonArray merged=target.has(field)?target.getAsJsonArray(field):new JsonArray();
        if(addition.has(field))for(JsonElement item:addition.getAsJsonArray(field))
            if(!merged.contains(item))merged.add(item.deepCopy());
        target.add(field,merged);
    }
}
