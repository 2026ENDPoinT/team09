package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Offline import and delayed-cache checks. Creates only temporary fixtures; never calls an AI API. */
public final class PdfUploadResponsivenessTest {
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-upload-responsive-");
        Path input=root.resolve("fixture.pdf");
        try(PDDocument document=new PDDocument()) {document.addPage(new PDPage());document.save(input.toFile());}
        testDelayedCache(root,input,false);
        testDelayedCache(root,input,true);
        testParallelPreviewBurst(root,input);
        testColdImport(root,input);
        System.out.println("PASS: cache I/O stays off Swing, pending input is handled, cancelled lookups stay cancelled, fresh imports skip empty recovery");
        System.exit(0);
    }

    private static void testDelayedCache(Path root,Path input,boolean cancelled)throws Exception {
        AtomicReference<PdfWorkspace> view=new AtomicReference<>();
        PdfSource source=PdfSource.open(input,root.resolve(cancelled?"cancelled":"cached"));
        JsonObject index=JsonParser.parseString("{\"fingerprint\":\"fixture\",\"pages\":[]}").getAsJsonObject();
        JsonObject saved=JsonParser.parseString("""
            {"kind":"ai_generated","promptVersion":"new-concept-study-ver.99","strategy":"new-concept-v99",
             "scope":"document","page":0,"sections":[],"concepts":[],"sourcePages":[1],
             "overview":{"title":"저장된 설명","body":"원문 내용은 그대로 보존해요.","evidence":[]}}
            """).getAsJsonObject();
        saved.addProperty("documentId",source.id);saved.addProperty("sourceFingerprint","fixture");
        // Large cached provenance is still useful on disk, but should not pause pointer/keyboard input.
        saved.addProperty("provenance","x".repeat(2_200_000));
        Path latest=source.folder.resolve("generated/new-concept-v99/latest-document-0.json");
        Files.createDirectories(latest.getParent());Files.writeString(latest,saved.toString());
        Files.writeString(latest.resolveSibling("latest-page-2.json"),"{corrupt");
        JsonObject wrong=saved.deepCopy();wrong.addProperty("documentId","other");
        Files.writeString(latest.resolveSibling("latest-page-3.json"),wrong.toString());
        Map<String,JsonObject> valid=PdfWorkspace.loadSavedProducts(source.folder,source.id,index);
        check(valid.size()==1,"corrupt and unrelated caches do not hide the valid result or enter the product map");
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        SwingUtilities.invokeAndWait(()->{
            PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("unused"));view.set(workspace);
            try {set(workspace,"source",source);set(workspace,"index",index);
                @SuppressWarnings("unchecked") JComboBox<String> strategy=(JComboBox<String>)get(workspace,"summaryStrategy");
                strategy.setSelectedIndex(7);
                ExecutorService jobs=(ExecutorService)get(workspace,"jobs");
                jobs.execute(()->{entered.countDown();try {release.await();}catch(InterruptedException error){Thread.currentThread().interrupt();}});
            }catch(Exception error){throw new RuntimeException(error);}
        });
        check(entered.await(5,TimeUnit.SECONDS),"fixture worker did not start");
        AtomicBoolean heartbeat=new AtomicBoolean();
        SwingUtilities.invokeAndWait(()->{try {
            invokeStart(view.get());
            check(!(boolean)view.get().ready(),"generation remains busy until the cache is actually ready");
            check(get(view.get(),"generated")==null,"cache parsing was not performed synchronously on Swing");
            if(cancelled)((AtomicInteger)get(view.get(),"generation")).incrementAndGet();
        }catch(Exception error){throw new RuntimeException(error);}});
        SwingUtilities.invokeAndWait(()->heartbeat.set(true));
        check(heartbeat.get(),"input events must run while cache storage is delayed");
        release.countDown();
        try {
            if(cancelled) {
                CompletableFuture.runAsync(()->{},(ExecutorService)get(view.get(),"jobs")).get(10,TimeUnit.SECONDS);
                SwingUtilities.invokeAndWait(()->{try {check(get(view.get(),"generated")==null,"stale cache completion changed the replacement document");}
                    catch(Exception error){throw new RuntimeException(error);}});
            } else {
                awaitReady(view.get());
                SwingUtilities.invokeAndWait(()->{try {
                    check(((JLabel)get(view.get(),"status")).getText().contains("새 API 비용 없음"),"saved result must be reused without a generation request");
                    check(get(view.get(),"generated")!=null,"saved result was not displayed");
                }catch(Exception error){throw new RuntimeException(error);}});
            }
            check(!Files.exists(source.folder.resolve("requests")),"a cache hit must not launch a Python/API request");
        } finally {SwingUtilities.invokeAndWait(()->view.get().close());}
    }

    private static void testColdImport(Path root,Path input)throws Exception {
        AtomicReference<PdfWorkspace> view=new AtomicReference<>();
        long started=System.nanoTime();
        SwingUtilities.invokeAndWait(()->{PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("cold"));view.set(workspace);workspace.openPdf(input);});
        try {
            awaitReady(view.get());
            Path copy=view.get().currentPdfCopy();
            check(copy!=null&&Files.isRegularFile(copy),"cold import must preserve its local source");
            check(!Files.exists(copy.getParent().resolve("requests")),"a document without generated history must not start recovery");
            System.out.printf(Locale.ROOT,"Cold local import (1 synthetic page, no API): %.3f s%n",(System.nanoTime()-started)/1e9);
        } finally {SwingUtilities.invokeAndWait(()->view.get().close());}
    }

    private static void testParallelPreviewBurst(Path root,Path input)throws Exception {
        AtomicReference<PdfWorkspace> view=new AtomicReference<>();AtomicLong first=new AtomicLong();
        PdfSource source=PdfSource.open(input,root.resolve("burst"));
        SwingUtilities.invokeAndWait(()->{try {
            PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("unused"));view.set(workspace);
            set(workspace,"source",source);set(workspace,"liveGenerationKey","new-concept-v99:document:0");
            @SuppressWarnings("unchecked") Map<Integer,JsonObject> sections=(Map<Integer,JsonObject>)get(workspace,"liveSummarySections");
            Method refresh=PdfWorkspace.class.getDeclaredMethod("refreshLiveSummaryPreview");refresh.setAccessible(true);
            sections.put(1,section(1));long before=(long)get(workspace,"summaryScrollRequest");refresh.invoke(workspace);
            first.set((long)get(workspace,"summaryScrollRequest"));
            check(first.get()==before+1,"first summary must not wait for a batching timer");
            for(int number=2;number<=32;number++){sections.put(number,section(number));refresh.invoke(workspace);}
            check((long)get(workspace,"summaryScrollRequest")==first.get(),"32 parallel arrivals must not trigger 32 rich-text reflows");
            check(((javax.swing.Timer)get(workspace,"liveSummaryRefreshTimer")).isRunning(),"later arrivals must request one display frame");
        }catch(Exception error){throw new RuntimeException(error);}});
        try {
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);AtomicBoolean finished=new AtomicBoolean();
            while(System.nanoTime()<deadline&&!finished.get()) {
                SwingUtilities.invokeAndWait(()->{try {finished.set(!((javax.swing.Timer)get(view.get(),"liveSummaryRefreshTimer")).isRunning());}
                    catch(Exception error){throw new RuntimeException(error);}});Thread.sleep(5);
            }
            check(finished.get(),"coalesced frame was never displayed");
            SwingUtilities.invokeAndWait(()->{try {
                check((long)get(view.get(),"summaryScrollRequest")==first.get()+1,"parallel burst must share a single later frame");
                @SuppressWarnings("unchecked") Map<Integer,JsonObject> sections=(Map<Integer,JsonObject>)get(view.get(),"liveSummarySections");
                check(sections.size()==32,"coalescing must retain every completed unit");
                Method refresh=PdfWorkspace.class.getDeclaredMethod("refreshLiveSummaryPreview");refresh.setAccessible(true);refresh.invoke(view.get());
                Method clear=PdfWorkspace.class.getDeclaredMethod("clearLiveSummary");clear.setAccessible(true);clear.invoke(view.get());
                check(!((javax.swing.Timer)get(view.get(),"liveSummaryRefreshTimer")).isRunning(),"document reset must cancel a pending refresh");
            }catch(Exception error){throw new RuntimeException(error);}});
        } finally {SwingUtilities.invokeAndWait(()->view.get().close());}
    }

    private static JsonObject section(int number) {
        JsonObject section=new JsonObject();section.addProperty("title","구간 "+number);section.addProperty("body","원문에 근거한 설명 "+number);return section;
    }

    private static void awaitReady(PdfWorkspace view)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(30);AtomicBoolean ready=new AtomicBoolean();
        while(System.nanoTime()<deadline) {SwingUtilities.invokeAndWait(()->ready.set(view.ready()));if(ready.get())return;Thread.sleep(10);}
        throw new AssertionError("offline result was not ready before deadline");
    }
    private static Object get(Object value,String name)throws Exception {Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field.get(value);}
    private static void set(Object value,String name,Object content)throws Exception {Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);field.set(value,content);}
    private static void invokeStart(PdfWorkspace view)throws Exception {Method method=PdfWorkspace.class.getDeclaredMethod("startGeneration",long.class,boolean.class);method.setAccessible(true);method.invoke(view,0L,false);}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}
