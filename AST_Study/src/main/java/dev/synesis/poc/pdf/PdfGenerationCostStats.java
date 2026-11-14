package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.AppPaths;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.*;
import java.util.*;

/** Local, weighted per-page costs. No API calls or PDF rendering; use off the EDT. */
final class PdfGenerationCostStats {
    private static final Gson JSON=new GsonBuilder().setPrettyPrinting().create();
    private static final String IMPORT_VERSION="generation-result-v2:";
    private PdfGenerationCostStats() {}

    static synchronized JsonObject recordAndCompare(Path root,JsonObject result,JsonObject request) throws IOException {
        return collect(root,PdfLibraryStore.list(root),result,request);
    }

    static synchronized void archive(Path root,PdfLibraryStore.Item item) throws IOException {
        collect(root,List.of(item),null,null);
    }

    private static JsonObject collect(Path root,List<PdfLibraryStore.Item> items,JsonObject current,JsonObject request) throws IOException {
        Path path=AppPaths.accountForLibrary(root).resolve("pdf-generation-page-costs.json");
        Files.createDirectories(path.getParent());
        // Separate test/app windows may finish simultaneously against one data
        // folder. Protect the read/merge/write, not just the atomic replacement.
        try(FileChannel channel=FileChannel.open(path.resolveSibling("pdf-generation-page-costs.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);
                var lock=channel.lock()) {
            return collectLocked(root,items,current,request,path);
        }
    }

    private static JsonObject collectLocked(Path root,List<PdfLibraryStore.Item> items,JsonObject current,JsonObject request,Path path) throws IOException {
        JsonObject state=new JsonObject();
        if(Files.exists(path))try {
            state=JsonParser.parseString(Files.readString(path)).getAsJsonObject();
            if(number(state,"version",0)!=1 || !state.has("records") || !state.get("records").isJsonObject()
                    || !state.has("imports") || !state.get("imports").isJsonObject())throw new IllegalArgumentException();
        }catch(RuntimeException invalid){throw new IOException("페이지당 비용 기록을 읽지 못했어요.",invalid);}
        else {state.addProperty("version",1);state.add("records",new JsonObject());state.add("imports",new JsonObject());}
        JsonObject records=state.getAsJsonObject("records"),imports=state.getAsJsonObject("imports");
        boolean changed=false;int unreadable=0;
        for(PdfLibraryStore.Item item:items) {
            Path folder=item.source().getParent(),requests=folder.resolve("requests");
            if(!Files.isDirectory(requests))continue;
            try(var paths=Files.list(requests)) {
                for(Path file:paths.filter(p->p.getFileName().toString().endsWith(".result.json")
                        && Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)).sorted().toList())try {
                    String key=root.toAbsolutePath().normalize().relativize(file.toAbsolutePath().normalize()).toString().replace('\\','/');
                    // Older collectors marked progressive wrappers imported
                    // without inspecting their nested completed generation.
                    String stamp=IMPORT_VERSION+Files.getLastModifiedTime(file).toMillis()+":"+Files.size(file);
                    Path input=file.resolveSibling(file.getFileName().toString().replace(".result.json",".json"));
                    if(Files.isRegularFile(input))stamp+=":"+Files.getLastModifiedTime(input).toMillis()+":"+Files.size(input);
                    if(stamp.equals(text(imports,key)))continue;
                    JsonObject result=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
                    JsonObject original=Files.isRegularFile(input)?JsonParser.parseString(Files.readString(input)).getAsJsonObject():null;
                    JsonObject row=entry(result,original);
                    if(row!=null)put(records,row);
                    imports.addProperty(key,stamp);changed=true;
                }catch(IOException|RuntimeException invalid){unreadable++;}
            }catch(IOException invalid){unreadable++;}
        }
        JsonObject row=current==null?null:entry(current,request);
        String currentKey=row==null?null:put(records,row);
        if(row!=null)changed=true;
        JsonObject report=new JsonObject();
        report.addProperty("currentPages",pages(current));
        report.addProperty("currentEligible",row!=null);
        report.addProperty("unreadableFiles",unreadable);
        report.add("previousTotal",average(records,currentKey,true));
        report.add("previousGeneration",average(records,currentKey,false));
        report.add("overallTotal",average(records,null,true));
        report.add("overallGeneration",average(records,null,false));
        long legacy=records.asMap().values().stream().map(JsonElement::getAsJsonObject).filter(r->!r.has("totalUsd")).count();
        report.addProperty("missingPlanningRuns",legacy);
        if(row!=null) {
            report.addProperty("currentGenerationUsd",number(row,"generationUsd",0));
            if(row.has("totalUsd"))report.add("currentTotalUsd",row.get("totalUsd").deepCopy());
        }
        if(changed) {
            Files.createDirectories(path.getParent());
            Path temporary=Files.createTempFile(path.getParent(),"page-cost-",".tmp");
            try {
                Files.writeString(temporary,JSON.toJson(state),StandardCharsets.UTF_8);
                try {Files.move(temporary,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
                catch(AtomicMoveNotSupportedException ignored){Files.move(temporary,path,StandardCopyOption.REPLACE_EXISTING);}
            }finally{Files.deleteIfExists(temporary);}
        }
        return report;
    }

    /** Missing old grouping costs are unknown, never invented as zero. */
    private static JsonObject entry(JsonObject result,JsonObject request) {
        JsonObject nested=object(result,"generationResult");
        if(nested!=null) {
            JsonObject context=request==null?new JsonObject():request.deepCopy();
            // The settled continuous-operation output owns its stage scope.
            // Its original request predates grouping and may have no usage.
            JsonObject planning=object(result,"planningRunUsage");
            if(planning==null)planning=object(nested,"generationPlanningUsage");
            if(planning!=null)context.add("planningRunUsage",planning.deepCopy());
            result=nested;request=context;
        }
        if(result==null || !"ai_generated".equals(text(result,"kind")) || !flag(result,"processingComplete")
                || flag(result,"cacheHit") || pages(result)==0 || text(result,"documentId").isEmpty()
                || text(result,"strategy").isEmpty() || !Set.of("document","section","page").contains(text(result,"scope")))return null;
        JsonObject usage=object(result,"runUsage");
        if(number(object(result,"pendingOriginalUsage"),"requests",0)>0)return null;
        if(!confirmed(usage) || number(usage,"requests",0)<=0 || number(usage,"usageBasedUsd",0)<=0)return null;
        JsonObject reuse=object(result,"cacheReuse");
        if(reuse!=null && reuse.has("replies") && reuse.get("replies").isJsonArray() && !reuse.getAsJsonArray("replies").isEmpty())return null;
        JsonObject metrics=object(result,"metrics");
        if(metrics!=null && metrics.has("newStudyJobs") && metrics.has("studyJobs")
                && number(metrics,"newStudyJobs",0)<number(metrics,"studyJobs",0)-1)return null;
        JsonObject kinds=object(usage,"byKind"),internal=object(kinds,"region_plan");
        double internalUsd=number(internal,"usageBasedUsd",0),usd=number(usage,"usageBasedUsd",0);
        if(internalUsd<0 || internalUsd>usd)return null;
        JsonObject planning=request!=null?object(request,"planningRunUsage"):null;
        if(planning==null)planning=object(result,"generationPlanningUsage");
        JsonObject row=new JsonObject();
        row.addProperty("documentId",text(result,"documentId"));
        row.addProperty("pages",pages(result));row.addProperty("generationUsd",usd-internalUsd);
        if(planning!=null && confirmed(planning))row.addProperty("totalUsd",usd+number(planning,"usageBasedUsd",0));
        else if(planning==null && number(internal,"requests",0)>0)row.addProperty("totalUsd",usd);
        String operation=text(result,"generationOperationId");
        if(!operation.isEmpty())row.addProperty("operationId",operation);
        JsonObject identity=new JsonObject();
        for(String key:new String[]{"documentId","model","strategy","scope","sourcePages"})
            if(result.has(key))identity.add(key,result.get(key).deepCopy());
        identity.add("usage",usage.deepCopy());
        row.addProperty("fingerprint",hash(canonical(identity)));
        return row;
    }

    /** Old cache snapshots may repeat the very same paid usage many times. */
    private static String put(JsonObject records,JsonObject row) {
        String operation=text(row,"operationId"),fingerprint=text(row,"fingerprint");
        String key=operation.isEmpty()?"legacy-"+fingerprint:"operation-"+hash(text(row,"documentId")+":"+operation);
        String alias=null;
        for(var item:records.entrySet()) {
            JsonObject saved=item.getValue().getAsJsonObject();
            if(fingerprint.equals(text(saved,"fingerprint"))
                    && (operation.isEmpty() || text(saved,"operationId").isEmpty())) {alias=item.getKey();break;}
        }
        if(alias!=null && operation.isEmpty())key=alias;
        JsonObject prior=object(records,key);
        if(prior==null && alias!=null)prior=object(records,alias);
        if(prior!=null && prior.has("totalUsd") && !row.has("totalUsd"))row.add("totalUsd",prior.get("totalUsd").deepCopy());
        if(prior!=null && prior.has("operationId") && !row.has("operationId"))row.add("operationId",prior.get("operationId").deepCopy());
        if(alias!=null && !alias.equals(key))records.remove(alias);
        records.add(key,row);return key;
    }

    private static JsonObject average(JsonObject records,String exclude,boolean total) {
        long runs=0,pages=0;double usd=0;String field=total?"totalUsd":"generationUsd";
        for(var item:records.entrySet()) {
            if(item.getKey().equals(exclude))continue;
            JsonObject row=item.getValue().getAsJsonObject();double amount=number(row,field,-1),count=number(row,"pages",0);
            if(amount<0 || count<1 || count!=Math.rint(count))continue;
            runs++;pages+=(long)count;usd+=amount;
        }
        JsonObject average=new JsonObject();average.addProperty("runs",runs);average.addProperty("pages",pages);
        average.addProperty("usd",usd);if(pages>0)average.addProperty("usdPerPage",usd/pages);
        return average;
    }

    static int pages(JsonObject result) {
        if(result==null || !result.has("sourcePages") || !result.get("sourcePages").isJsonArray())return 0;
        Set<Integer> pages=new HashSet<>();
        for(JsonElement p:result.getAsJsonArray("sourcePages"))try {
            double value=p.getAsDouble();if(value<1 || value!=Math.rint(value) || value>Integer.MAX_VALUE)return 0;
            pages.add((int)value);
        }catch(RuntimeException invalid){return 0;}
        return pages.size();
    }
    private static boolean confirmed(JsonObject usage) {
        return usage!=null && number(usage,"usageBasedUsd",-1)>=0
            && number(usage,"unknownUsageRequests",usage.has("unknownUsageRequests")?-1:0)==0
            && number(usage,"uncertainReservedUsd",usage.has("uncertainReservedUsd")?-1:0)==0;
    }
    static JsonObject object(JsonObject object,String key) {return object!=null && object.has(key) && object.get(key).isJsonObject()?object.getAsJsonObject(key):null;}
    private static boolean flag(JsonObject object,String key) {try{return object!=null && object.has(key) && object.get(key).getAsBoolean();}catch(RuntimeException invalid){return false;}}
    private static String text(JsonObject object,String key) {try{return object!=null && object.has(key) && !object.get(key).isJsonNull()?object.get(key).getAsString():"";}catch(RuntimeException invalid){return "";}}
    private static double number(JsonObject object,String key,double fallback) {try{double n=object.get(key).getAsDouble();return Double.isFinite(n)?n:fallback;}catch(RuntimeException invalid){return fallback;}}
    private static String hash(String value) {try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}}
    private static String canonical(JsonElement element) {
        if(element.isJsonObject()) {List<String> keys=new ArrayList<>(element.getAsJsonObject().keySet());Collections.sort(keys);StringJoiner out=new StringJoiner(",","{","}");for(String key:keys)out.add(new JsonPrimitive(key)+":"+canonical(element.getAsJsonObject().get(key)));return out.toString();}
        if(element.isJsonArray()) {StringJoiner out=new StringJoiner(",","[","]");for(JsonElement value:element.getAsJsonArray())out.add(canonical(value));return out.toString();}
        if(element.isJsonPrimitive() && element.getAsJsonPrimitive().isNumber())try{return element.getAsBigDecimal().stripTrailingZeros().toPlainString();}catch(RuntimeException ignored){}
        return element.toString();
    }
}
