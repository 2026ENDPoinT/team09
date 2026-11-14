package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.awt.*;
import java.awt.event.ActionEvent;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import javax.swing.*;

/** True arriving-text preview, replacement and burst bounds; no API, process or window. */
public final class SummaryIncrementalStreamTest {
    private static PdfWorkspace workspace;
    private static PdfSource source;
    private static int epoch;
    private static JPanel flow;
    private static JScrollPane scroll;

    public static void main(String[] args)throws Exception {
        try {
            setup();
            delta(1,1,"FIRST arriving text <script>literal</script> and unfinished \\(x_1",false);drain();frame();
            edt(()->{
                check(text(flow).contains("FIRST arriving text"),"partial text is not visible before unit-ready");
                check(text(flow).contains("<script>literal</script>"),"untrusted preview markup was interpreted instead of displayed literally");
                check(drafts().containsKey(1),"first partial did not create a draft");
                check(map("liveSummarySections").isEmpty()&&map("liveConceptUnits").isEmpty(),"unverified draft polluted canonical summary/concepts");
                check(map("products").isEmpty()&&get("generated")==null,"draft entered saved output");
            });
            // Delivery is cumulative, ordered by sequence rather than arrival.
            delta(1,3,"THIRD cumulative body",false);delta(1,2,"STALE text must not replace",false);drain();frame();
            edt(()->check(text(flow).contains("THIRD cumulative body")&&!text(flow).contains("STALE text"),"stale sequence overwrote newer draft"));
            AtomicLong initialRevision=new AtomicLong();AtomicReference<StudyHtmlPane> retainedPane=new AtomicReference<>();
            edt(()->{retainedPane.set(draftPane(1));initialRevision.set(draftPane(1).contentRevision());});
            // Enqueue a burst in one EDT operation, so its token updates share a
            // coalesced frame rather than reparsing the entire summary 500 times.
            edt(()->{for(int i=4;i<504;i++)deliver(event(1,i,"BURST latest "+i,false));});drain();frame();
            edt(()->{
                check(text(flow).contains("BURST latest 503"),"coalescing dropped the newest cumulative body");
                check(draftPane(1)==retainedPane.get(),"body-only burst recreated the draft pane");
                check(draftPane(1).contentRevision()-initialRevision.get()<=4,"500 token deltas reparsed a draft too often");
                check(map("liveSummarySections").isEmpty()&&map("liveConceptUnits").isEmpty(),"burst promoted drafts to verified output");
            });
            delta(2,1,"SECOND draft remains beside canonical hierarchy",false);drain();frame();
            ready(1,canonical(1));drain();frame();
            edt(()->{
                check(!drafts().containsKey(1)&&drafts().containsKey(2),"ready event failed to replace only its own draft");
                check(text(flow).contains("VERIFIED canonical body 1")&&text(flow).contains("SECOND draft remains"),"canonical hierarchy and draft do not coexist");
                check(!text(flow).contains("BURST latest"),"canonical replacement left duplicate draft text");
                check(count(text(flow),"VERIFIED canonical body 1")==1,"canonical text is duplicated");
                JsonObject saved=(JsonObject)map("liveSummarySections").get(1);
                check(saved.has("hierarchy"),"test did not exercise native canonical hierarchy");
                @SuppressWarnings("unchecked") Map<Integer,Integer> visible=(Map<Integer,Integer>)get("liveSummaryVisible");
                check(visible.get(1)==saved.get("body").getAsString().length(),"canonical body was restarted as fake typing");
            });
            Map<StudyHtmlPane,Long> canonicalRevisions=new IdentityHashMap<>();
            edt(()->collectCanonicalRevisions(flow,canonicalRevisions));
            edt(()->{for(int i=2;i<502;i++)deliver(event(2,i,"SECOND draft remains beside canonical hierarchy "+i,false));});drain();frame();
            edt(()->{
                check(!canonicalRevisions.isEmpty(),"no canonical prose collected for performance test");
                for(var item:canonicalRevisions.entrySet())check(item.getKey().contentRevision()==item.getValue(),"body-only streaming reparsed canonical rich content");
            });
            delta(1,9999,"LATE stale stream after canonical",false);drain();frame();
            edt(()->check(!drafts().containsKey(1)&&!text(flow).contains("LATE stale"),"late delta resurrected an already verified unit"));
            delta(3,1,"THIRD draft survives other failure",false);delta(2,502,"",true);drain();frame();
            edt(()->{
                check(!drafts().containsKey(2)&&drafts().containsKey(3),"discard cleared the wrong draft");
                check(text(flow).contains("THIRD draft survives")&&!text(flow).contains("SECOND draft remains"),"discard left stale preview on screen");
                check(map("liveSummarySections").containsKey(1),"discard removed verified content");
                call("clearLiveSummary");
                check(drafts().isEmpty()&&map("liveSummaryDraftSequences").isEmpty()&&map("liveSummaryDraftPanes").isEmpty(),"final/cancel cleanup retained draft state");
                javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryDraftTimer");
                check(timer==null||!timer.isRunning(),"cleanup retained streaming refresh timer");
                begin();((AtomicInteger)get("generation")).incrementAndGet();
            });
            delta(1,20000,"OLD generation must not return",false);drain();frame();
            edt(()->check(drafts().isEmpty(),"stale generation progress repopulated drafts"));
            check(!Files.exists(source.folder.resolve("requests")),"display event launched a model request");
            System.out.println("PASS: arriving partial text, safe literals, sequence ordering, bounded 500-delta burst, hierarchy replacement, discard and stale-generation cleanup");
        } catch(Throwable failure) {failure.printStackTrace();System.exit(1);}
        finally {if(workspace!=null)edt(workspace::close);}
        System.exit(0);
    }
    private static void setup()throws Exception {
        Path root=Files.createTempDirectory("summary-incremental-");Path pdf=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<3;i++)doc.addPage(new PDPage());doc.save(pdf.toFile());}
        source=PdfSource.open(pdf,root.resolve("library"));
        edt(()->{
            workspace=new PdfWorkspace(false,root.resolve("unused"));set("source",source);
            set("index",JsonParser.parseString("{\"pages\":[{\"number\":1,\"markdown\":\"\"},{\"number\":2,\"markdown\":\"\"},{\"number\":3,\"markdown\":\"\"}],\"chunks\":[]}").getAsJsonObject());
            ((JComboBox<?>)get("summaryStrategy")).setSelectedIndex(7);
            flow=(JPanel)get("summaryFlow");scroll=(JScrollPane)get("summaryScroll");
            begin();epoch=((AtomicInteger)get("generation")).get();
            call("setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.RUNNING);
            layout();
        });drain();
    }
    private static void begin()throws Exception {call("clearLiveSummary");set("liveGenerationKey",call("productKey",new Class<?>[]{String.class,int.class},"document",0));}
    private static JsonObject event(int unit,long sequence,String body,boolean discard) {
        JsonObject event=new JsonObject();event.addProperty("type","summary_unit_delta");event.addProperty("unit",unit);event.addProperty("total",3);
        event.addProperty("scope","document");event.addProperty("selectionPage",0);event.addProperty("strategy","new-concept-v99");
        event.addProperty("sequence",sequence);event.addProperty("preview",true);
        if(discard)event.addProperty("discard",true);
        JsonObject summary=new JsonObject();summary.addProperty("title","도착 중인 구간 "+unit);summary.addProperty("body",body);
        JsonArray pages=new JsonArray();pages.add(unit);summary.add("visualPages",pages);event.add("summary",summary);return event;
    }
    private static void delta(int unit,long sequence,String body,boolean discard)throws Exception {deliver(event(unit,sequence,body,discard));}
    private static void deliver(JsonObject event)throws Exception {call("handleProgress",new Class<?>[]{int.class,JsonObject.class},epoch,event);}
    private static void ready(int number,JsonObject unit)throws Exception {
        Path path=source.folder.resolve("generated/new-concept-v99/stream-test").resolve(String.format(Locale.ROOT,"unit-%05d.json",number-1));Files.createDirectories(path.getParent());Files.writeString(path,unit.toString());
        JsonObject e=new JsonObject();e.addProperty("type","summary_unit_ready");e.addProperty("unit",number);e.addProperty("total",3);e.addProperty("scope","document");e.addProperty("selectionPage",0);e.addProperty("strategy","new-concept-v99");e.addProperty("path",path.toString());deliver(e);
    }
    private static JsonObject canonical(int number) {
        JsonObject summary=new JsonObject();summary.addProperty("title","검증된 구간 "+number);summary.addProperty("body","VERIFIED canonical body "+number);
        summary.add("evidence",new JsonArray());summary.add("visualPages",new JsonArray());summary.addProperty("standardKnowledgeUsed",false);
        JsonObject part=summary.deepCopy();part.addProperty("nodeId","verified-"+number);part.addProperty("contentId","content-"+number);part.addProperty("easyExplanation","");JsonArray parts=new JsonArray();parts.add(part);summary.add("parts",parts);
        JsonObject node=new JsonObject();node.addProperty("id","verified-"+number);node.addProperty("parentId","");node.addProperty("title","검증된 계층 "+number);node.addProperty("level",1);node.addProperty("page",number);
        JsonArray nodes=new JsonArray();nodes.add(node);JsonObject hierarchy=new JsonObject();hierarchy.add("nodes",nodes);summary.add("hierarchy",hierarchy);
        JsonObject unit=new JsonObject();unit.add("summary",summary);unit.add("concepts",new JsonArray());return unit;
    }
    private static void frame()throws Exception {edt(()->{
        javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryDraftTimer");
        if(timer!=null&&timer.isRunning()){timer.stop();for(var listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,ActionEvent.ACTION_PERFORMED,"deterministic frame"));}
        layout();
    });drain();}
    private static void layout(){scroll.setSize(646,420);scroll.doLayout();flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);flow.doLayout();scroll.getViewport().setViewSize(flow.getSize());scroll.doLayout();}
    @SuppressWarnings("unchecked") private static Map<Integer,JsonObject> drafts()throws Exception{return (Map<Integer,JsonObject>)get("liveSummaryDrafts");}
    private static StudyHtmlPane draftPane(int unit)throws Exception{return (StudyHtmlPane)map("liveSummaryDraftPanes").get(unit);}
    private static Map<?,?> map(String name)throws Exception{return (Map<?,?>)get(name);}
    private static String text(Container container)throws Exception {StringBuilder text=new StringBuilder();for(Component child:container.getComponents()) {
        if(!child.isVisible())continue;if(child instanceof JEditorPane pane)text.append(pane.getDocument().getText(0,pane.getDocument().getLength()));else if(child instanceof Container nested)text.append(text(nested));
    }return text.toString();}
    private static void collectCanonicalRevisions(Container container,Map<StudyHtmlPane,Long> result)throws Exception {
        for(Component child:container.getComponents()) {
            if(child instanceof StudyHtmlPane pane && !map("liveSummaryDraftPanes").containsValue(pane))result.put(pane,pane.contentRevision());
            else if(child instanceof Container nested)collectCanonicalRevisions(nested,result);
        }
    }
    private static int count(String text,String token){return (text.length()-text.replace(token,"").length())/token.length();}
    private static Object get(String name)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(workspace);}
    private static void set(String name,Object value)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(workspace,value);}
    private static Object call(String name)throws Exception{return call(name,new Class<?>[]{});}
    private static Object call(String name,Class<?>[] types,Object...args)throws Exception{Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(workspace,args);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work work)throws Exception{SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception e){throw new RuntimeException(e);}});}
    private static void drain()throws Exception{edt(()->{});edt(()->{});}
    private static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
}
