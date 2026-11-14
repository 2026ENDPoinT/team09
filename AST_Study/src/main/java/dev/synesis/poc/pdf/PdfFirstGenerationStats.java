package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Instant;
import java.util.*;

/** One earliest paid, completed ver.99 document generation per PDF; cache opens and reruns excluded. */
final class PdfFirstGenerationStats {
    record Average(int count,double usd) {}

    static synchronized Average read(Path root,List<PdfLibraryStore.Item> items,Instant since) throws IOException {
        Path index=dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("pdf-first-generation-history.json");
        JsonObject records=Files.exists(index)?JsonParser.parseString(Files.readString(index)).getAsJsonObject():new JsonObject();
        boolean changed=false;
        for(PdfLibraryStore.Item item:items) {
            Path folder=item.source().getParent();
            List<Path> candidates=new ArrayList<>();
            Path requests=folder.resolve("requests");
            if(Files.isDirectory(requests))try(var paths=Files.list(requests)) {
                paths.filter(p->p.getFileName().toString().endsWith(".result.json")).forEach(candidates::add);
            }
            // Request snapshots are immutable run records. Generated cache files can be overwritten.
            if(candidates.isEmpty() && Files.isDirectory(folder.resolve("generated/new-concept-v99")))
                try(var paths=Files.walk(folder.resolve("generated/new-concept-v99"),2)) {
                    paths.filter(p->p.getFileName().toString().equals("result.json")).forEach(candidates::add);
                }
            JsonObject earliest=records.has(item.id())?records.getAsJsonObject(item.id()):null;
            for(Path path:candidates) {
                JsonObject result;
                try {result=JsonParser.parseString(Files.readString(path)).getAsJsonObject();}
                catch(RuntimeException invalid) {continue;}
                if(!text(result,"strategy").equals("new-concept-v99") || !text(result,"scope").equals("document")
                    || !result.has("processingComplete") || !result.get("processingComplete").getAsBoolean()
                    || (result.has("cacheHit") && result.get("cacheHit").getAsBoolean())
                    || !result.has("sections") || result.getAsJsonArray("sections").isEmpty()
                    || !result.has("runUsage"))continue;
                JsonObject usage=result.getAsJsonObject("runUsage");
                JsonObject kinds=usage.has("byKind")?usage.getAsJsonObject("byKind"):null;
                if(kinds==null || !kinds.has("region_study") || kinds.getAsJsonObject("region_study").get("requests").getAsInt()<=0)continue;
                long created=result.has("generationStartedAtMs")?result.get("generationStartedAtMs").getAsLong()
                    :Files.readAttributes(path,BasicFileAttributes.class).creationTime().toMillis();
                if(earliest==null || created<earliest.get("createdAtMs").getAsLong()) {
                    earliest=new JsonObject();earliest.addProperty("createdAtMs",created);
                    earliest.addProperty("usd",usage.get("usageBasedUsd").getAsDouble());
                    earliest.addProperty("unknown",usage.has("unknownUsageRequests")?usage.get("unknownUsageRequests").getAsInt():0);
                    earliest.addProperty("source",path.toString());
                    records.add(item.id(),earliest);changed=true;
                }
            }
        }
        if(changed) {
            Files.createDirectories(index.getParent());
            Path temp=Files.createTempFile(index.getParent(),"first-generation-",".tmp");
            try {
                Files.writeString(temp,new GsonBuilder().setPrettyPrinting().create().toJson(records));
                try {Files.move(temp,index,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
                catch(AtomicMoveNotSupportedException ignored) {Files.move(temp,index,StandardCopyOption.REPLACE_EXISTING);}
            } finally {Files.deleteIfExists(temp);}
        }
        int count=0;double usd=0;
        for(JsonElement value:records.asMap().values()) {
            JsonObject record=value.getAsJsonObject();
            if(Instant.ofEpochMilli(record.get("createdAtMs").getAsLong()).isBefore(since)
                || record.get("unknown").getAsInt()>0)continue;
            count++;usd+=record.get("usd").getAsDouble();
        }
        return new Average(count,count==0?0:usd/count);
    }
    private static String text(JsonObject object,String key) {return object.has(key)?object.get(key).getAsString():"";}
}
