package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Offline costs: weighted history, stage scope, cached copies and paid operation identity. */
public final class PdfGenerationCostStatsTest {
    private static final Gson JSON=new Gson();
    private static final String ID="a".repeat(64);
    static JsonObject usage(double usd,int requests) {
        JsonObject u=new JsonObject();u.addProperty("usageBasedUsd",usd);u.addProperty("requests",requests);
        u.addProperty("inputTokens",requests*100);u.addProperty("outputTokens",requests*10);
        u.addProperty("unknownUsageRequests",0);u.addProperty("uncertainReservedUsd",0);return u;
    }
    static JsonObject result(double usd,int pages,String operation) {
        JsonObject r=new JsonObject();r.addProperty("documentId",ID);r.addProperty("model","gpt-6-luna");
        r.addProperty("strategy","new-concept-v99");r.addProperty("scope","document");
        r.addProperty("kind","ai_generated");r.addProperty("processingComplete",true);
        r.add("runUsage",usage(usd,2));JsonArray ps=new JsonArray();for(int i=1;i<=pages;i++)ps.add(i);r.add("sourcePages",ps);
        if(operation!=null)r.addProperty("generationOperationId",operation);return r;
    }
    static JsonObject request(double plan) {JsonObject q=new JsonObject();q.add("planningRunUsage",usage(plan,plan>0?1:0));return q;}
    private static void save(Path root,String name,JsonObject r,JsonObject q) throws Exception {
        Path folder=root.resolve(ID);Files.createDirectories(folder.resolve("requests"));Files.write(folder.resolve("source.pdf"),new byte[]{1});
        Files.writeString(folder.resolve("requests/"+name+".result.json"),JSON.toJson(r));
        if(q!=null)Files.writeString(folder.resolve("requests/"+name+".json"),JSON.toJson(q));
    }
    private static JsonObject group(JsonObject r,String name){return r.getAsJsonObject(name);}
    private static void near(double a,double b){if(Math.abs(a-b)>1e-10)throw new AssertionError(a+" != "+b);}
    private static void count(JsonObject g,int runs,int pages,double usd){near(g.get("runs").getAsDouble(),runs);near(g.get("pages").getAsDouble(),pages);near(g.get("usd").getAsDouble(),usd);if(pages>0)near(g.get("usdPerPage").getAsDouble(),usd/pages);}
    private static void check(boolean b,String s){if(!b)throw new AssertionError(s);}
    public static void main(String[] args) throws Exception {
        Path base=Files.createTempDirectory("synesis-page-cost-");
        try {
            Path root=base.resolve("weighted/pdf");
            JsonObject a=result(.09,10,"a"),b=result(.1,100,"b"),current=result(.045,10,"current");
            save(root,"a",a,request(.01));save(root,"b",b,request(0));save(root,"current",current,request(.005));
            JsonObject r=PdfGenerationCostStats.recordAndCompare(root,current,request(.005));
            count(group(r,"previousTotal"),2,110,.2);count(group(r,"overallTotal"),3,120,.25);
            count(group(r,"previousGeneration"),2,110,.19);
            near(r.get("currentGenerationUsd").getAsDouble(),.045);
            String html=PdfWorkspace.generationRunReportHtml(withComparison(current,r),request(.005));
            check(html.contains("7.000원/쪽") && html.contains("총비용 확인 3건") && html.contains("175.0%"),"Per-page amount, weighted count and previous-only deviation");
            check(html.contains("이전 평균보다 4.455원/쪽 높아요") && !html.contains("$"),"Concise won-only page-rate comparison");
            count(group(PdfGenerationCostStats.recordAndCompare(root,current,request(.005)),"overallTotal"),3,120,.25);

            // Old cache opens sometimes copied nonzero historic usage without a cacheHit flag.
            Path legacy=base.resolve("legacy/pdf");JsonObject old=result(.2,20,null);
            save(legacy,"copy-a",old,null);save(legacy,"copy-b",old.deepCopy(),null);
            JsonObject modern=result(.2,20,"new-paid-1");save(legacy,"new-one",modern,request(.02));
            JsonObject paidAgain=result(.2,20,"new-paid-2");save(legacy,"new-two",paidAgain,request(.03));
            JsonObject migrated=PdfGenerationCostStats.recordAndCompare(legacy,null,null);
            count(group(migrated,"overallGeneration"),2,40,.4);
            count(group(migrated,"overallTotal"),2,40,.45);

            Path excluded=base.resolve("exclude/pdf");
            JsonObject partial=result(.1,10,"partial");partial.addProperty("processingComplete",false);save(excluded,"partial",partial,request(0));
            JsonObject cached=result(.1,10,"cached");cached.addProperty("cacheHit",true);save(excluded,"cached",cached,request(0));
            JsonObject unknown=result(.1,10,"unknown");unknown.getAsJsonObject("runUsage").addProperty("unknownUsageRequests",1);save(excluded,"unknown",unknown,request(0));
            JsonObject noPages=result(.1,0,"empty");save(excluded,"empty",noPages,request(0));
            JsonObject good=result(.03,30,"good");save(excluded,"good",good,null);
            JsonObject noPlan=PdfGenerationCostStats.recordAndCompare(excluded,good,null);
            count(group(noPlan,"overallGeneration"),1,30,.03);count(group(noPlan,"overallTotal"),0,0,0);
            check(noPlan.get("missingPlanningRuns").getAsInt()==1,"Absent grouping cost stays unknown, not zero");
            String noPlanHtml=PdfWorkspace.generationRunReportHtml(withComparison(good,noPlan));
            check(noPlanHtml.contains("기록 없음") && noPlanHtml.contains("전체 평균: 집계할 기록이 아직 없어요"),
                "Missing grouping cost must not turn a generation-only average into a total-cost comparison");
            JsonObject withKnownPlan=good.deepCopy();withKnownPlan.add("generationPlanningUsage",usage(.01,1));save(excluded,"good",withKnownPlan,null);
            JsonObject enriched=PdfGenerationCostStats.recordAndCompare(excluded,withKnownPlan,null);
            count(group(enriched,"overallTotal"),1,30,.04);

            Path internalRoot=base.resolve("internal/pdf");JsonObject internal=result(.12,12,"internal");
            JsonObject byKind=new JsonObject(),planning=usage(.02,1);byKind.add("region_plan",planning);
            internal.getAsJsonObject("runUsage").add("byKind",byKind);save(internalRoot,"internal",internal,null);
            JsonObject internalStats=PdfGenerationCostStats.recordAndCompare(internalRoot,internal,null);
            count(group(internalStats,"overallTotal"),1,12,.12);
            count(group(internalStats,"overallGeneration"),1,12,.10);

            // Continuous group-plan results wrap the finished generation. An
            // old collector may already have stamped such a file as imported
            // while recording no row. Revisit it under the new import version.
            Path progressive=base.resolve("progressive/pdf");
            JsonObject nested=result(.04,20,"progressive-operation");
            nested.add("generationPlanningUsage",usage(.01,1));
            JsonObject wrapper=new JsonObject();wrapper.add("generationResult",nested);
            wrapper.add("planningRunUsage",usage(.015,2));
            save(progressive,"continuous",wrapper,null);
            Path wrappedFile=progressive.resolve(ID).resolve("requests/continuous.result.json");
            JsonObject stale=new JsonObject();stale.addProperty("version",1);stale.add("records",new JsonObject());
            JsonObject imports=new JsonObject();imports.addProperty(ID+"/requests/continuous.result.json",
                Files.getLastModifiedTime(wrappedFile).toMillis()+":"+Files.size(wrappedFile));stale.add("imports",imports);
            Path history=dev.synesis.poc.AppPaths.accountForLibrary(progressive).resolve("pdf-generation-page-costs.json");
            Files.createDirectories(history.getParent());Files.writeString(history,JSON.toJson(stale));
            String durable=Files.readString(wrappedFile);
            JsonObject backfilled=PdfGenerationCostStats.recordAndCompare(progressive,null,null);
            count(group(backfilled,"overallGeneration"),1,20,.04);
            count(group(backfilled,"overallTotal"),1,20,.055);
            check(Files.readString(wrappedFile).equals(durable),"Backfill must leave the original result and paid usage unchanged");
            // A direct snapshot of the same operation must not become another
            // paid run, even when both legacy and continuous shapes coexist.
            save(progressive,"same-operation",nested,request(.015));
            JsonObject duplicate=PdfGenerationCostStats.recordAndCompare(progressive,null,null);
            count(group(duplicate,"overallGeneration"),1,20,.04);
            count(group(duplicate,"overallTotal"),1,20,.055);
            JsonObject innerOnly=result(.02,10,"inner-only-operation");
            innerOnly.add("generationPlanningUsage",usage(.005,1));
            JsonObject innerWrapper=new JsonObject();innerWrapper.add("generationResult",innerOnly);
            save(progressive,"inner-planning",innerWrapper,null);
            JsonObject unfinished=result(.09,30,"unfinished-progressive");unfinished.addProperty("processingComplete",false);
            JsonObject partialWrapper=new JsonObject();partialWrapper.add("generationResult",unfinished);partialWrapper.add("planningRunUsage",usage(.01,1));
            save(progressive,"partial-continuous",partialWrapper,null);
            JsonObject progressiveStats=PdfGenerationCostStats.recordAndCompare(progressive,null,null);
            count(group(progressiveStats,"overallGeneration"),2,30,.06);
            count(group(progressiveStats,"overallTotal"),2,30,.08);
            // A damaged unrelated snapshot must not erase the known samples.
            Files.writeString(internalRoot.resolve(ID).resolve("requests/bad.result.json"),"not json");
            JsonObject damaged=PdfGenerationCostStats.recordAndCompare(internalRoot,internal,null);
            count(group(damaged,"overallTotal"),1,12,.12);
            check(damaged.get("unreadableFiles").getAsInt()==1,"Damaged snapshot excluded explicitly");

            JsonObject unsettledPlan=request(.01);unsettledPlan.getAsJsonObject("planningRunUsage").addProperty("unknownUsageRequests",1);
            JsonObject pending=result(.04,20,"pending-plan");save(internalRoot,"pending-plan",pending,unsettledPlan);
            JsonObject pendingStats=PdfGenerationCostStats.recordAndCompare(internalRoot,pending,unsettledPlan);
            count(group(pendingStats,"overallTotal"),1,12,.12);
            count(group(pendingStats,"overallGeneration"),2,32,.14);

            // Deleting the PDF must not erase its cumulative cost sample.
            PdfLibraryStore.Item item=PdfLibraryStore.list(root).get(0);
            PdfGenerationCostStats.archive(root,item);PdfLibraryStore.deleteFile(root,ID);
            count(group(PdfGenerationCostStats.recordAndCompare(root,null,null),"overallTotal"),3,120,.25);
            check(PdfGenerationCostStats.pages(JsonParser.parseString("{\"sourcePages\":[1,1,2]}").getAsJsonObject())==2,"Unique physical page denominator");
            System.out.println("PASS: weighted means, independent deviation, legacy deduplication, stage costs, exclusions, persistence");
        } finally {try(var paths=Files.walk(base)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}}
    }
    static JsonObject withComparison(JsonObject result,JsonObject report){JsonObject r=result.deepCopy();r.add("pageCostComparison",report);return r;}
}
