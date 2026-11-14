package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import javax.swing.SwingUtilities;
import org.apache.pdfbox.pdmodel.*;

/** Queue integration with synthetic worker events; never calls a provider or opens a window. */
public final class PdfBatchLiveEventsTest {
    static void check(boolean good,String message){if(!good)throw new AssertionError(message);}
    static void await(java.util.function.BooleanSupplier ready)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        while(!ready.getAsBoolean() && System.nanoTime()<deadline)Thread.sleep(10);
        check(ready.getAsBoolean(),"Fixture did not reach expected queue state");
    }
    static JsonObject event(String type,int sequence) {
        JsonObject event=new JsonObject();event.addProperty("type",type);event.addProperty("strategy","newest-k1");
        event.addProperty("scope","document");event.addProperty("selectionPage",0);
        if(!type.equals("summary_overview_ready")) {event.addProperty("unit",1);event.addProperty("total",2);event.addProperty("sequence",sequence);}
        return event;
    }
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-batch-live-"),file=base.resolve("lesson.pdf");
        try(PDDocument doc=new PDDocument()){doc.addPage(new PDPage());doc.save(file.toFile());}
        CountDownLatch generating=new CountDownLatch(1),finish=new CountDownLatch(1);
        List<JsonObject> received=Collections.synchronizedList(new ArrayList<>());
        try(var queue=new PdfBatchQueue(base.resolve("library"),plans->null,snapshots->{},()->{},true,
                (process,script,arguments,events)->{
                    Path folder=Path.of(arguments.get(arguments.indexOf("--folder")+1));
                    if(script.equals("pdf_pipeline.py"))Files.writeString(folder.resolve("document.json"),"{\"pages\":[{}]}");
                    if(!arguments.contains("--request"))return;
                    Path request=Path.of(arguments.get(arguments.indexOf("--request")+1));
                    if(arguments.get(0).equals("generate")) {
                        events.accept(event("summary_overview_ready",0));
                        events.accept(event("summary_unit_delta",1));events.accept(event("summary_unit_delta",2));
                        events.accept(event("summary_unit_ready",3));
                        generating.countDown();check(finish.await(10,TimeUnit.SECONDS),"Fixture release timed out");
                    }
                    Files.writeString(request.resolveSibling(request.getFileName().toString().replace(".json",".result.json")),
                        arguments.get(0).equals("group-plan")?"{\"totalCostEstimateUsd\":0}":"{}");
                })) {
            queue.setStudyListener((snapshot,event)->{check(snapshot.strategy().equals("newest-k1"),"Event source engine lost");received.add(event);});
            queue.submitImports(List.of(new PdfBatchQueue.ImportChoice(file,"",false)));
            await(()->queue.snapshots().size()==1 && queue.snapshots().get(0).state()==PdfBatchQueue.State.COMPLETE);
            Path stored=queue.snapshots().get(0).storedPdf();
            queue.submitImports(List.of(new PdfBatchQueue.ImportChoice(file,"",true,"newest-k1")));
            check(generating.await(10,TimeUnit.SECONDS),"K1 worker never started");SwingUtilities.invokeAndWait(()->{});
            var active=queue.forStoredPdf(stored);
            check(active.order()==2 && active.strategy().equals("newest-k1") && PdfBatchQueue.active(active.state()),"Old completed engine masked active K1 queue");
            check(queue.forStoredPdf(file).order()==2,"Original-path lookup did not select active queue");
            check(received.size()==4,"Live overview/delta/ready were not forwarded");
            received.clear();queue.replayStudy(stored);SwingUtilities.invokeAndWait(()->{});
            check(received.size()==2 && received.get(0).get("type").getAsString().equals("summary_overview_ready")
                && received.get(1).get("type").getAsString().equals("summary_unit_ready"),"Replay retained old deltas or lost overview/unit order");
            finish.countDown();await(()->queue.snapshots().stream().allMatch(s->s.state()==PdfBatchQueue.State.COMPLETE));
            check(queue.forStoredPdf(stored).order()==2,"Latest completed engine is not selected");
            var oldActive=new PdfBatchQueue.Snapshot(1,"id","old",stored,PdfBatchQueue.State.RUNNING,0,"",0);
            check(PdfBatchQueue.preferredSnapshot(List.of(oldActive,queue.forStoredPdf(stored))).order()==1,"Completed newer record masks ongoing work");
            received.clear();queue.replayStudy(stored);SwingUtilities.invokeAndWait(()->{});
            check(received.isEmpty(),"Completed queue replayed stale live events");
        }finally {finish.countDown();}
        System.out.println("PdfBatchLiveEventsTest passed: active/latest lookup, live forwarding, bounded replay, terminal isolation");
    }
}
