package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
import javax.swing.*;

/** Cached page/section display migration, without a subprocess, API or window. */
public final class SavedHierarchyScopeUpgradeTest {
    private static final class Recovery {
        final String strategy,scope;final int page;final String fingerprint;
        final CountDownLatch release=new CountDownLatch(1);
        final AtomicReference<JsonObject> reply=new AtomicReference<>();
        Recovery(String strategy,String scope,int page,String fingerprint) {
            this.strategy=strategy;this.scope=scope;this.page=page;this.fingerprint=fingerprint;
        }
        void finish(JsonObject result){reply.set(result);release.countDown();}
    }
    private static final class Fixture {
        final PdfWorkspace workspace;
        final BlockingQueue<Recovery> requests=new LinkedBlockingQueue<>();
        final List<Recovery> all=new CopyOnWriteArrayList<>();
        Fixture(Path root){workspace=new PdfWorkspace(false,root);workspace.savedHierarchyRecovery=this::recover;}
        JsonObject recover(PdfSource source,int ticket,String strategy,String scope,int page,String fingerprint) {
            check(!SwingUtilities.isEventDispatchThread(),"Local recovery blocked Swing");
            Recovery request=new Recovery(strategy,scope,page,fingerprint);all.add(request);requests.add(request);
            try {check(request.release.await(10,TimeUnit.SECONDS),"Fixture recovery was not released");}
            catch(InterruptedException interrupted){Thread.currentThread().interrupt();return null;}
            return request.reply.get();
        }
        void close(){workspace.close();}
    }
    public static void main(String[] args)throws Exception {
        contracts();
        localCompletionContracts();
        Path root=Files.createTempDirectory("synesis-saved-hierarchy-scope-");
        Path input=root.resolve("input.pdf");
        try(PDDocument document=new PDDocument()){for(int i=0;i<10;i++)document.addPage(new PDPage());document.save(input.toFile());}
        PdfSource source=PdfSource.open(input,root.resolve("library"));
        AtomicReference<Fixture> reference=new AtomicReference<>();
        SwingUtilities.invokeAndWait(()->reference.set(new Fixture(root.resolve("library"))));
        Fixture workspace=reference.get();
        JsonObject page=product(source.id,"page",8,true),section=product(source.id,"section",6,false);
        page.getAsJsonObject("hierarchy").addProperty("version","study-hierarchy-6");
        JsonObject document=JsonParser.parseString("{\"fingerprint\":\"fp\",\"pages\":[]}").getAsJsonObject();
        Path stored=source.folder.resolve("generated/new-concept-v99/latest-page-8.json");Files.createDirectories(stored.getParent());Files.writeString(stored,page.toString());
        Path usage=source.folder.resolve("usage/original.json");Files.createDirectories(usage.getParent());Files.writeString(usage,"{\"estimatedUsd\":0.03}");
        byte[] paidBytes=Files.readAllBytes(stored),usageBytes=Files.readAllBytes(usage),pdfBytes=Files.readAllBytes(source.folder.resolve("source.pdf"));
        try {
            edt(()->{
                JComboBox<?> scope=field(workspace,"scope");for(var listener:scope.getActionListeners())scope.removeActionListener(listener);
                JComboBox<?> strategy=field(workspace,"summaryStrategy");for(var listener:strategy.getActionListeners())strategy.removeActionListener(listener);
                strategy.setSelectedIndex(7);
                set(workspace,"source",source);set(workspace,"index",document);set(workspace,"busy",true);
                products(workspace).put(key("page",8),page);products(workspace).put(key("section",6),section);
                select(workspace,1,8);
            });
            Recovery first=take(workspace);check(first.scope.equals("page")&&first.page==8&&first.strategy.equals("new-concept-v99"),"Wrong captured page scope");
            edt(()->check(field(workspace,"generated")==page,"Cached result was not available while local upgrade was pending"));
            edt(()->{invokeSelect(workspace);select(workspace,2,8);});
            check(workspace.all.size()==1,"Repeated selection spawned duplicate recovery");
            first.finish(upgraded(page));Recovery second=take(workspace);
            await(()->version(products(workspace).get(key("page",8))).equals(PdfWorkspace.LOCAL_HIERARCHY_VERSION));
            edt(()->check(field(workspace,"generated")==section,"Late page projection replaced the selected section"));
            check(second.scope.equals("section")&&second.page==6,"Section recovery did not use its canonical cached page");
            second.finish(upgraded(section));
            await(()->version((JsonObject)field(workspace,"generated")).equals(PdfWorkspace.LOCAL_HIERARCHY_VERSION));
            check(Arrays.equals(paidBytes,Files.readAllBytes(stored))&&Arrays.equals(usageBytes,Files.readAllBytes(usage))
                &&Arrays.equals(pdfBytes,Files.readAllBytes(source.folder.resolve("source.pdf"))),"Local projection changed saved prose, paid usage or PDF");
            check(!Files.exists(source.folder.resolve("requests")),"Scope selection launched a real worker/API fixture");
            check(version(page).equals("study-hierarchy-6")&&version(section).equals("study-hierarchy-5"),"Original in-memory cached objects were mutated");
            int recoveredCalls=workspace.all.size();
            edt(()->{select(workspace,1,8);invokeSelect(workspace);});drain(workspace);
            check(workspace.all.size()==recoveredCalls&&workspace.requests.isEmpty(),"Current h7 result started another local recovery");

            JsonObject stale=product(source.id,"page",9,true);
            edt(()->{products(workspace).put(key("page",9),stale);select(workspace,1,9);});
            Recovery oldEpoch=take(workspace);
            edt(()->{((AtomicInteger)field(workspace,"generation")).incrementAndGet();set(workspace,"generated",section);});
            oldEpoch.finish(upgraded(stale));drain(workspace);
            edt(()->check(products(workspace).get(key("page",9))==stale&&field(workspace,"generated")==section,"Stale epoch projection was applied"));

            JsonObject replaced=product(source.id,"page",10,true),fresh=upgraded(replaced);
            edt(()->{products(workspace).put(key("page",10),replaced);select(workspace,1,10);});
            Recovery oldProduct=take(workspace);
            edt(()->{products(workspace).put(key("page",10),fresh);set(workspace,"generated",fresh);});
            JsonObject oldReply=upgraded(replaced);oldReply.addProperty("fixtureStale",true);oldProduct.finish(oldReply);drain(workspace);
            edt(()->check(products(workspace).get(key("page",10))==fresh&&field(workspace,"generated")==fresh,"Projection overwrote a newly generated product"));

            JsonObject invalid=product(source.id,"page",7,true);
            edt(()->{products(workspace).put(key("page",7),invalid);select(workspace,1,7);});
            Recovery failed=take(workspace);failed.finish(invalid);drain(workspace);
            edt(()->invokeSelect(workspace));drain(workspace);
            check(workspace.requests.isEmpty(),"Unchanged failed migration was retried on each selection");

            JsonObject oldDocument=product(source.id,"page",5,true);
            edt(()->{products(workspace).put(key("page",5),oldDocument);select(workspace,1,5);});
            Recovery documentChange=take(workspace);
            edt(()->{set(workspace,"index",document.deepCopy());set(workspace,"generated",fresh);});
            documentChange.finish(upgraded(oldDocument));drain(workspace);
            edt(()->check(products(workspace).get(key("page",5))==oldDocument&&field(workspace,"generated")==fresh,"Projection survived a document-index replacement"));

            JsonObject closing=product(source.id,"page",4,true);
            edt(()->{products(workspace).put(key("page",4),closing);select(workspace,1,4);});
            Recovery closingRequest=take(workspace);
            edt(()->{set(workspace,"source",null);set(workspace,"generated",fresh);});
            closingRequest.finish(upgraded(closing));drain(workspace);
            edt(()->check(products(workspace).get(key("page",4))==closing&&field(workspace,"generated")==fresh,"Projection survived a source switch"));
        } finally {
            workspace.all.forEach(request->request.release.countDown());
            edt(()->{set(workspace,"source",null);workspace.close();});source.close();
        }
        System.out.println("SavedHierarchyScopeUpgradeTest passed: async page/section migration, deduplication, stale epoch/source/index/product guards and unchanged paid files");
    }
    private static void contracts() {
        JsonObject document=JsonParser.parseString("{\"fingerprint\":\"fp\"}").getAsJsonObject();
        for(String scope:List.of("document","page","section"))for(String previous:List.of("study-hierarchy-5","study-hierarchy-6","study-hierarchy-7")) {
            JsonObject saved=product("d",scope,scope.equals("document")?0:6,true),value=upgraded(saved);
            saved.getAsJsonObject("hierarchy").addProperty("version",previous);
            check(PdfWorkspace.needsSavedHierarchyProjection(saved),"Old scope was skipped");
            check(PdfWorkspace.validSavedHierarchyProjection(value,saved,document),"Valid scope migration rejected");
            check(!PdfWorkspace.needsSavedHierarchyProjection(value),"Current projection repeated");
            for(String revision:List.of("source-unit-continuity-1","source-unit-continuity-2")) {
                JsonObject previousDisplay=value.deepCopy();
                previousDisplay.getAsJsonObject("hierarchy").addProperty("displayRevision",revision);
                check(PdfWorkspace.needsSavedHierarchyProjection(previousDisplay),"Old source hierarchy reused: "+revision);
            }
            check(!value.has("learningViewRevision"),"Legacy display requires new quality metadata");
            JsonObject wrong=value.deepCopy();wrong.addProperty("scope",scope.equals("page")?"section":"page");
            check(!PdfWorkspace.validSavedHierarchyProjection(wrong,saved,document),"Wrong scope was accepted");
            wrong=value.deepCopy();wrong.addProperty("sourceFingerprint","other");
            check(!PdfWorkspace.validSavedHierarchyProjection(wrong,saved,document),"Wrong source was accepted");
            wrong=value.deepCopy();wrong.remove("page");
            check(!PdfWorkspace.validSavedHierarchyProjection(wrong,saved,document),"Malformed response was accepted");
            wrong=value.deepCopy();wrong.getAsJsonObject("hierarchy").addProperty("version","study-hierarchy-6");
            check(!PdfWorkspace.validSavedHierarchyProjection(wrong,saved,document),"Old h6 projection was accepted as h7");
            wrong=value.deepCopy();wrong.getAsJsonObject("hierarchy").remove("displayRevision");
            check(!PdfWorkspace.validSavedHierarchyProjection(wrong,saved,document),"Old h7 unit layout was accepted as current");
        }
    }
    private static void localCompletionContracts()throws Exception {
        Path root=Files.createTempDirectory("legacy-local-complete-");
        Path generated=root.resolve("generated/new-concept-v99");Files.createDirectories(generated);
        JsonObject latest=product("d","document",0,false);latest.addProperty("promptVersion","new-concept-study-ver.99");latest.addProperty("model","gpt-6-luna");
        byte[] latestBytes=latest.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        Path latestPath=generated.resolve("latest-document-0.json");Files.write(latestPath,latestBytes);
        JsonObject full=upgraded(latest);full.addProperty("kind","ai_generated");full.addProperty("processingComplete",true);
        full.add("localRecovery",JsonParser.parseString("{\"newPaidCalls\":0}"));
        full.addProperty("localCompletionFixture",true);
        String rootName="a".repeat(64);Path result=generated.resolve(rootName).resolve("result.json");Files.createDirectories(result.getParent());
        byte[] fullBytes=full.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);Files.write(result,fullBytes);
        java.security.MessageDigest hash=java.security.MessageDigest.getInstance("SHA-256");
        JsonObject pointer=new JsonObject();pointer.addProperty("rootName",rootName);
        pointer.addProperty("originalLatestSha256",java.util.HexFormat.of().formatHex(hash.digest(latestBytes)));
        pointer.addProperty("resultSha256",java.util.HexFormat.of().formatHex(hash.digest(fullBytes)));
        Path pointerPath=generated.resolve("local-complete-document-0.json");Files.writeString(pointerPath,pointer.toString());
        JsonObject document=JsonParser.parseString("{\"fingerprint\":\"fp\"}").getAsJsonObject();
        JsonObject selected=PdfWorkspace.loadSavedProducts(root,"d",document).values().iterator().next();
        check(selected.equals(full),"Exact local-complete recovery was not selected");
        check(Arrays.equals(latestBytes,Files.readAllBytes(latestPath)),"Raw partial latest was rewritten");
        pointer.addProperty("originalLatestSha256","0".repeat(64));Files.writeString(pointerPath,pointer.toString());
        check(PdfWorkspace.loadSavedProducts(root,"d",document).values().iterator().next().equals(latest),"Stale pointer replaced current latest");
        pointer.addProperty("originalLatestSha256",java.util.HexFormat.of().formatHex(hash.digest(latestBytes)));
        full.addProperty("documentId","other");fullBytes=full.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);Files.write(result,fullBytes);
        pointer.addProperty("resultSha256",java.util.HexFormat.of().formatHex(hash.digest(fullBytes)));Files.writeString(pointerPath,pointer.toString());
        check(PdfWorkspace.loadSavedProducts(root,"d",document).values().iterator().next().equals(latest),"Foreign local-complete identity was selected");
    }

    private static JsonObject product(String id,String scope,int page,boolean complete) {
        JsonObject result=new JsonObject();result.addProperty("documentId",id);result.addProperty("sourceFingerprint","fp");
        result.addProperty("strategy","new-concept-v99");result.addProperty("scope",scope);result.addProperty("page",page);
        result.addProperty("kind",complete?"ai_generated":"partial");result.addProperty("processingComplete",complete);
        result.add("hierarchy",JsonParser.parseString("{\"version\":\"study-hierarchy-5\",\"nodes\":[]}"));
        result.add("sections",JsonParser.parseString("[{\"title\":\"원문\",\"parts\":[{\"body\":\"저장 설명\"}]}]"));
        result.add("runUsage",JsonParser.parseString("{\"usageBasedUsd\":0.03,\"requests\":2}"));return result;
    }
    private static JsonObject upgraded(JsonObject saved) {JsonObject value=saved.deepCopy();value.getAsJsonObject("hierarchy").addProperty("version",PdfWorkspace.LOCAL_HIERARCHY_VERSION);value.getAsJsonObject("hierarchy").addProperty("displayRevision",PdfWorkspace.LOCAL_HIERARCHY_DISPLAY_REVISION);return value;}
    private static String version(JsonObject result){return result.getAsJsonObject("hierarchy").get("version").getAsString();}
    private static String key(String scope,int page){return PdfWorkspace.strategyProductKey("new-concept-v99",scope,page);}
    private static Recovery take(Fixture workspace)throws Exception {Recovery request=workspace.requests.poll(5,TimeUnit.SECONDS);check(request!=null,"No local scope recovery started");return request;}
    private static void select(Fixture workspace,int scope,int page){((JComboBox<?>)field(workspace,"scope")).setSelectedIndex(scope);set(workspace,"page",page);invokeSelect(workspace);}
    private static void invokeSelect(Fixture workspace){try{Method method=PdfWorkspace.class.getDeclaredMethod("selectProduct");method.setAccessible(true);method.invoke(workspace.workspace);}catch(ReflectiveOperationException failure){throw new RuntimeException(failure);}}
    private static void drain(Fixture workspace)throws Exception {((ExecutorService)field(workspace,"jobs")).submit(()->{}).get(5,TimeUnit.SECONDS);edt(()->{});}
    private static void await(BooleanSupplier condition)throws Exception {long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);AtomicBoolean okay=new AtomicBoolean();do{edt(()->okay.set(condition.getAsBoolean()));if(okay.get())return;Thread.sleep(5);}while(System.nanoTime()<until);throw new AssertionError("Local projection did not arrive");}
    private static Map<String,JsonObject> products(Fixture workspace){return field(workspace,"products");}
    @SuppressWarnings("unchecked") private static <T>T field(Object object,String name){try{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return(T)field.get(object instanceof Fixture fixture?fixture.workspace:object);}catch(ReflectiveOperationException failure){throw new RuntimeException(failure);}}
    private static void set(Object object,String name,Object value){try{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);field.set(object instanceof Fixture fixture?fixture.workspace:object,value);}catch(ReflectiveOperationException failure){throw new RuntimeException(failure);}}
    private static void edt(Runnable action)throws Exception {SwingUtilities.invokeAndWait(action);}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
