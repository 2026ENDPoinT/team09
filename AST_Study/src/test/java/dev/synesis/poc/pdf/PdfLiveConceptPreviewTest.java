package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Unit-ready UI contract. Temporary fixtures only; no process runner, API or native window. */
public final class PdfLiveConceptPreviewTest {
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-live-concepts-");
        Path input=root.resolve("fixture.pdf");
        try(PDDocument doc=new PDDocument()){doc.addPage(new PDPage());doc.save(input.toFile());}
        PdfSource source=PdfSource.open(input,root.resolve("library"));
        AtomicReference<PdfWorkspace> view=new AtomicReference<>();
        SwingUtilities.invokeAndWait(()->{try {
            PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("unused"));view.set(workspace);
            set(workspace,"source",source);
            set(workspace,"index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
            ((JComboBox<?>)get(workspace,"summaryStrategy")).setSelectedIndex(7);
            begin(workspace,"document",0);
        }catch(Exception error){throw new RuntimeException(error);}});
        PdfWorkspace workspace=view.get();int epoch=((AtomicInteger)get(workspace,"generation")).get();
        try {
            JsonObject later=unit(2);deliver(workspace,source,epoch,2,later);drain();
            AtomicReference<Object> retained=new AtomicReference<>();
            SwingUtilities.invokeAndWait(()->{try {
                check(cards(workspace).size()==1,"a completed later unit must show concepts before earlier units finish");
                check(get(workspace,"generated")==null,"live concepts must not replace the canonical saved result");
                check(((Map<?,?>)get(workspace,"products")).isEmpty(),"preview must not enter the saved product map");
                JsonObject preview=preview(workspace);
                check(preview.getAsJsonArray("concepts").get(0).getAsJsonObject().get("name").getAsString().equals("개념 2"),"wrong first completed card");
                Object card=cards(workspace).values().iterator().next();retained.set(card);
                Method open=card.getClass().getDeclaredMethod("setOpen",boolean.class);open.setAccessible(true);open.invoke(card,true);
            }catch(Exception error){throw new RuntimeException(error);}});
            // A replay replaces that unit, while an earlier unit is inserted in
            // source order. Neither may recreate the already expanded card.
            deliver(workspace,source,epoch,2,later);deliver(workspace,source,epoch,1,unit(1));drain();awaitFrame(workspace);
            SwingUtilities.invokeAndWait(()->{try {
                check(cards(workspace).size()==2,"replayed unit duplicated concepts or an earlier unit was lost");
                check(cards(workspace).containsValue(retained.get()),"parallel arrivals recreated an unchanged concept card");
                check((boolean)field(retained.get(),"open"),"parallel arrivals collapsed the reader's open concept");
                JsonArray concepts=preview(workspace).getAsJsonArray("concepts");
                check(concepts.get(0).getAsJsonObject().get("name").getAsString().equals("개념 1"),"concepts follow arrival order instead of source order");
                JsonObject entry=concepts.get(1).getAsJsonObject().getAsJsonArray("entries").get(0).getAsJsonObject();
                check(entry.get("explanation").getAsString().contains("설명 2"),"live entry lost its explanation");
                check(entry.getAsJsonArray("evidence").get(0).getAsJsonObject().get("sourceId").getAsString().equals("v2p1f2"),"live entry changed its source evidence");
                JsonObject canonical=preview(workspace).deepCopy();canonical.remove("livePreview");canonical.addProperty("kind","ai_generated");
                clear(workspace);set(workspace,"generated",canonical);show(workspace);
                check(cards(workspace).size()==2 && cards(workspace).containsValue(retained.get()),"final result needlessly recreated an unchanged card");
                check(((Map<?,?>)get(workspace,"liveConceptUnits")).isEmpty(),"final transition retained live-only concept data");
                // A cancelled generation cannot reinsert either a summary or
                // a concept when its pending progress event reaches Swing.
                set(workspace,"liveGenerationKey","new-concept-v99:document:0");
                ((AtomicInteger)get(workspace,"generation")).incrementAndGet();
            }catch(Exception error){throw new RuntimeException(error);}});
            deliver(workspace,source,epoch,3,unit(3));drain();
            SwingUtilities.invokeAndWait(()->{try {
                check(((Map<?,?>)get(workspace,"liveConceptUnits")).isEmpty(),"stale progress repopulated cancelled concepts");
                check(cards(workspace).size()==2,"stale progress changed the final visible cards");
                clear(workspace);
            }catch(Exception error){throw new RuntimeException(error);}});
            check(!Files.exists(source.folder.resolve("requests")),"a display update launched a model request");
            System.out.println("PASS: unit-ready concepts retain source order/evidence/open cards, replace replays, and ignore stale events");
        } finally {SwingUtilities.invokeAndWait(workspace::close);}
        System.exit(0);
    }

    private static JsonObject unit(int number) {
        JsonObject entry=new JsonObject();entry.addProperty("name","개념 "+number);
        entry.addProperty("definition","정의 "+number);entry.addProperty("explanation","원문 설명 "+number);
        entry.addProperty("easyExplanation","쉬운 설명 "+number);entry.addProperty("standardKnowledgeUsed",false);
        entry.add("aliases",new JsonArray());JsonArray pages=new JsonArray();pages.add(1);entry.add("visualPages",pages);
        JsonArray evidence=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("sourceId","v2p1f"+number);ref.addProperty("page",1);ref.addProperty("quote","원문 근거");evidence.add(ref);entry.add("evidence",evidence);
        JsonObject part=new JsonObject();part.addProperty("title","개념 "+number);part.addProperty("body","정의 "+number+"\n\n원문 설명 "+number);
        part.addProperty("easyExplanation","쉬운 설명 "+number);part.add("evidence",evidence.deepCopy());part.add("visualPages",pages.deepCopy());part.addProperty("standardKnowledgeUsed",false);
        JsonObject summary=new JsonObject();summary.addProperty("title","구간 "+number);summary.addProperty("body",part.get("body").getAsString());
        JsonArray parts=new JsonArray();parts.add(part);summary.add("parts",parts);summary.add("evidence",evidence.deepCopy());summary.add("visualPages",pages.deepCopy());summary.addProperty("standardKnowledgeUsed",false);
        JsonObject unit=new JsonObject();unit.add("summary",summary);JsonArray concepts=new JsonArray();concepts.add(entry);unit.add("concepts",concepts);return unit;
    }
    private static void deliver(PdfWorkspace workspace,PdfSource source,int epoch,int number,JsonObject unit)throws Exception {
        Path path=source.folder.resolve("generated/new-concept-v99/live-fixture").resolve(String.format(Locale.ROOT,"unit-%05d.json",number-1));
        Files.createDirectories(path.getParent());Files.writeString(path,unit.toString());
        JsonObject event=new JsonObject();event.addProperty("type","summary_unit_ready");event.addProperty("unit",number);event.addProperty("total",3);
        event.addProperty("scope","document");event.addProperty("selectionPage",0);event.addProperty("path",path.toString());
        Method handler=PdfWorkspace.class.getDeclaredMethod("handleProgress",int.class,JsonObject.class);handler.setAccessible(true);handler.invoke(workspace,epoch,event);
    }
    private static void awaitFrame(PdfWorkspace workspace)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);AtomicBoolean ready=new AtomicBoolean();
        while(System.nanoTime()<deadline){SwingUtilities.invokeAndWait(()->{try {javax.swing.Timer timer=(javax.swing.Timer)get(workspace,"liveSummaryRefreshTimer");ready.set(timer==null||!timer.isRunning());}catch(Exception e){throw new RuntimeException(e);}});if(ready.get())return;Thread.sleep(5);}
        throw new AssertionError("coalesced summary/concept frame did not run");
    }
    private static JsonObject preview(PdfWorkspace workspace)throws Exception {Method m=PdfWorkspace.class.getDeclaredMethod("conceptResultForDisplay");m.setAccessible(true);return (JsonObject)m.invoke(workspace);}
    private static void begin(PdfWorkspace workspace,String scope,int page)throws Exception {
        clear(workspace);
        Method key=PdfWorkspace.class.getDeclaredMethod("productKey",String.class,int.class);
        key.setAccessible(true);set(workspace,"liveGenerationKey",key.invoke(workspace,scope,page));
    }
    @SuppressWarnings("unchecked") private static Map<String,?> cards(PdfWorkspace workspace)throws Exception{return (Map<String,?>)get(workspace,"conceptCards");}
    private static void clear(PdfWorkspace workspace)throws Exception {Method m=PdfWorkspace.class.getDeclaredMethod("clearLiveSummary");m.setAccessible(true);m.invoke(workspace);}
    private static void show(PdfWorkspace workspace)throws Exception {Method m=PdfWorkspace.class.getDeclaredMethod("showConcepts");m.setAccessible(true);m.invoke(workspace);}
    private static Object field(Object value,String name)throws Exception {Field f=value.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(value);}
    private static Object get(PdfWorkspace value,String name)throws Exception{return field(value,name);}
    private static void set(PdfWorkspace value,String name,Object content)throws Exception {Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(value,content);}
    private static void drain()throws Exception {SwingUtilities.invokeAndWait(()->{});}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
