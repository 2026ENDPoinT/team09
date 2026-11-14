package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.Component;
import java.awt.Container;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Synthetic source and worker events only. Does not open a window or call a model. */
public final class NewestK1_1_3UiTest {
    static PdfWorkspace view;
    static Object get(String name)throws Exception {var f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(view);}
    static void set(String name,Object value)throws Exception {var f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(view,value);}
    static Object call(String name,Class<?>[] types,Object... args)throws Exception {var m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(view,args);}
    interface Action {void run()throws Exception;}
    static void edt(Action action)throws Exception {SwingUtilities.invokeAndWait(()->{try{action.run();}catch(Exception e){throw new RuntimeException(e);}});}
    static void check(boolean good,String message){if(!good)throw new AssertionError(message);}
    static void drainWorker()throws Exception {((ExecutorService)get("jobs")).submit(()->{}).get(5,TimeUnit.SECONDS);edt(()->{});}
    static String visibleText(Container parent)throws Exception {
        StringBuilder text=new StringBuilder();
        for(Component child:parent.getComponents()) {
            if(!child.isVisible())continue;
            if(child instanceof JEditorPane pane)text.append(pane.getDocument().getText(0,pane.getDocument().getLength()));
            else if(child instanceof JLabel label)text.append(label.getText());
            else if(child instanceof Container nested)text.append(visibleText(nested));
        }
        return text.toString();
    }
    static int occurrences(String text,String value) {
        int count=0,at=0;while((at=text.indexOf(value,at))>=0){count++;at+=value.length();}return count;
    }
    static void checkLiveOverview(String body,int progress)throws Exception {
        Container flow=(Container)get("summaryFlow");
        SummaryOverviewLoading card=(SummaryOverviewLoading)get("summaryOverviewLoading");
        SummaryActivityBar bar=(SummaryActivityBar)get("summaryActivity");
        String all=visibleText(flow),inside=visibleText(card);
        check(card.getParent()==flow && bar.getParent()==card,"Overview and progress no longer share the existing card");
        check(occurrences(inside,body)==1 && occurrences(all,body)==1,"Early overview must appear inside the loading card exactly once");
        check(occurrences(all,"이 강의의 흐름")==1,"Duplicated overview heading/card");
        check(!all.contains("강의의 흐름을 PDF를 읽으며 정리하고 있어요."),"Loading placeholder remained beside the generated overview");
        check(inside.contains("강의 해설 생성 중에도 PDF와 연결된 AI멘토를 이용할 수 있어요."),"Live overview removed the tutor availability notice");
        check(!card.completed() && bar.isVisible() && bar.state()==SummaryActivityBar.State.RUNNING && bar.progress()==progress,
            "Live overview completed or reset the running progress bar");
    }
    static JsonObject event(String type,Path path) {
        JsonObject event=new JsonObject();event.addProperty("type",type);event.addProperty("strategy","newest-k1-1-3");
        event.addProperty("scope","document");event.addProperty("selectionPage",0);
        if(path!=null)event.addProperty("path",path.toString());
        return event;
    }
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-k1-ui-"),pdf=root.resolve("fixture.pdf");
        try(PDDocument document=new PDDocument()){document.addPage(new PDPage());document.save(pdf.toFile());}
        PdfSource source=PdfSource.open(pdf,root.resolve("library"));
        JsonObject overview=JsonParser.parseString("{\"title\":\"이 강의의 흐름\",\"body\":\"금리의 의미를 살펴보고 채권 가격의 변화를 연결해요.\",\"evidence\":[],\"visualPages\":[]}").getAsJsonObject();
        Path partial=source.folder.resolve("generated/newest-k1-1-3/partial.json");Files.createDirectories(partial.getParent());
        JsonObject result=new JsonObject();result.add("overview",overview);Files.writeString(partial,result.toString());
        try {
            edt(()->{
                check(PdfStudyStrategy.DEFAULT.equals("newest-k1-1-2"),"Existing default must stay K1.1.2");
                view=new PdfWorkspace(false,root.resolve("unused"));view.selectGenerationEngine("newest-k1-1-3");
                check(PdfWorkspace.readableStudyVersion("Newest_K1.1.3-v1"),"K1 saved output rejected");
                check(PdfWorkspace.readableStudyVersion(PdfStudyStrategy.VER99_PROMPT),"Legacy saved output rejected");
                check(call("expectedStudyVersion",new Class<?>[]{}).equals("Newest_K1.1.3-v1"),"Wrong expected version");
                check((boolean)get("generationEngineSelected"),"Opening choice not retained");
                set("source",source);set("index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
                set("summaryReadingSkin",true);
                call("setGenerationProgress",new Class<?>[]{PdfWorkspace.GenerationProgress.class},
                    new PdfWorkspace.GenerationProgress(source.id,source.name,37,"생성 중",false,false));
                set("liveGenerationKey",PdfWorkspace.strategyProductKey("newest-k1-1-3","document",0));
                JsonObject event=new JsonObject();event.addProperty("type","summary_overview_ready");event.addProperty("strategy","newest-k1-1-3");
                event.addProperty("scope","document");event.addProperty("selectionPage",0);event.addProperty("path",partial.toString());
                call("handleProgress",new Class<?>[]{int.class,JsonObject.class},((AtomicInteger)get("generation")).get(),event);
            });
            edt(()->{
                check(overview.equals(get("liveOverview")),"Early overview not accepted");
                check(((Map<?,?>)get("liveSummarySections")).isEmpty(),"Overview created a fake teaching unit");
                check((boolean)call("hasLiveSummaryContent",new Class<?>[]{}),"Overview remains hidden behind loading state");
                checkLiveOverview(overview.get("body").getAsString(),37);
                JsonObject event=new JsonObject();event.addProperty("type","summary_unit_delta");event.addProperty("strategy","newest-k1-1-3");
                event.addProperty("scope","document");event.addProperty("selectionPage",0);event.addProperty("unit",1);event.addProperty("total",2);event.addProperty("sequence",1);
                JsonObject draft=new JsonObject();draft.addProperty("title","금리");draft.addProperty("body","금리는 자금을 빌리는 대가예요.");draft.add("visualPages",new JsonArray());event.add("summary",draft);
                call("handleProgress",new Class<?>[]{int.class,JsonObject.class},((AtomicInteger)get("generation")).get(),event);
            });
            edt(()->{
                check(((Map<?,?>)get("liveSummaryDrafts")).size()==1,"K1 bypassed existing streaming path");
                check(overview.equals(get("liveOverview")),"Teaching stream removed overview");
                call("renderSummary",new Class<?>[]{boolean.class},true);
                checkLiveOverview(overview.get("body").getAsString(),37);
                call("clearLiveSummary",new Class<?>[]{});
                check(get("liveOverview")==null,"Overview leaks into another generation");
                JsonObject complete=JsonParser.parseString("{\"kind\":\"ai_generated\",\"strategy\":\"newest-k1-1-3\",\"scope\":\"document\",\"page\":0,\"sections\":[],\"concepts\":[]}").getAsJsonObject();
                complete.add("overview",overview.deepCopy());set("generated",complete);
                call("finishGeneration",new Class<?>[]{boolean.class,String.class},false,"완료");
                SummaryOverviewLoading card=(SummaryOverviewLoading)get("summaryOverviewLoading");
                SummaryActivityBar bar=(SummaryActivityBar)get("summaryActivity");
                String completedText=visibleText((Container)get("summaryFlow"));
                check(card.completed() && !bar.isVisible() && bar.state()==SummaryActivityBar.State.IDLE,"Completion did not settle the same overview card");
                check(occurrences(completedText,overview.get("body").getAsString())==1 && occurrences(completedText,"이 강의의 흐름")==1,"Completion duplicated or removed the overview");
                check(!completedText.contains("AI멘토를 이용할 수 있어요."),"Completed overview retained the loading notice");
                set("generated",null);
                call("setGenerationProgress",new Class<?>[]{PdfWorkspace.GenerationProgress.class},
                    new PdfWorkspace.GenerationProgress(source.id,source.name,0,"새 생성 준비",false,false));
                String restartedText=visibleText((Container)get("summaryFlow"));
                check(!card.completed() && bar.isVisible() && bar.state()==SummaryActivityBar.State.RUNNING && bar.progress()==0,"New generation did not reset the card and progress");
                check(!restartedText.contains(overview.get("body").getAsString()) && restartedText.contains("강의의 흐름을 PDF를 읽으며 정리하고 있어요."),"New generation retained stale overview text");
                view.selectGenerationEngine("new-concept-v99");
                check(call("expectedStudyVersion",new Class<?>[]{}).equals(PdfStudyStrategy.VER99_PROMPT),"Legacy engine cannot be selected");
            });
            var running=new PdfBatchQueue.Snapshot(2,source.id,source.name,source.folder.resolve("source.pdf"),PdfBatchQueue.State.RUNNING,30,"생성 중",0,"newest-k1-1-3");
            edt(()->{
                view.showBatchGeneration(running);
                check(call("expectedStudyVersion",new Class<?>[]{}).equals(PdfStudyStrategy.K1_1_3_PROMPT),"Reopened active queue kept the old engine");
                check((boolean)get("externalBatchActive"),"Queue ownership not recorded");
                check(!((JButton)get("generate")).isEnabled(),"Queue allows a duplicate local generation");
                int epoch=((AtomicInteger)get("generation")).get();
                view.chooseEngineForOpenedPdf();call("startGeneration",new Class<?>[]{long.class,boolean.class},0L,false);
                check(get("studyAdmission")==null && epoch==((AtomicInteger)get("generation")).get(),"Reopening active queue started local generation");
                view.acceptBatchStudyEvent(running,event("summary_overview_ready",partial));
            });
            drainWorker();
            edt(()->{
                check(overview.equals(get("liveOverview")),"Queue overview did not reach existing display path");
                JsonObject delta=event("summary_unit_delta",null);delta.addProperty("unit",1);delta.addProperty("total",2);delta.addProperty("sequence",1);
                delta.add("summary",JsonParser.parseString("{\"title\":\"금리\",\"body\":\"금리는 자금을 빌리는 대가예요.\",\"visualPages\":[]}"));
                view.acceptBatchStudyEvent(running,delta);
                JsonObject wrong=event("summary_overview_ready",partial);wrong.addProperty("strategy","new-concept-v99");
                view.acceptBatchStudyEvent(running,wrong);
                var otherFile=new PdfBatchQueue.Snapshot(3,"another-source","다른 PDF",pdf,PdfBatchQueue.State.RUNNING,30,"",0,"newest-k1-1-3");
                view.acceptBatchStudyEvent(otherFile,event("summary_overview_ready",partial));
                var old=new PdfBatchQueue.Snapshot(1,source.id,source.name,running.storedPdf(),PdfBatchQueue.State.COMPLETE,100,"",0);
                view.observeBatchState(old);
                check((boolean)get("externalBatchActive") && ((Long)get("observedBatchOrder"))==2,"Old completed queue unlocked the active run");
            });
            drainWorker();
            edt(()->{
                check(((Map<?,?>)get("liveSummaryDrafts")).size()==1,"Queue delta lost existing streaming animation path");
                check(overview.equals(get("liveOverview")) && ((Long)get("liveBatchOrder"))==2,"Wrong file/engine took over the stream");
            });
            JsonObject unit=new JsonObject();unit.add("summary",JsonParser.parseString("{\"title\":\"금리\",\"body\":\"완성된 설명이에요.\",\"evidence\":[],\"visualPages\":[]}"));unit.add("concepts",new JsonArray());
            Path unitPath=partial.getParent().resolve("unit-00000.json");Files.writeString(unitPath,unit.toString());
            edt(()->{JsonObject ready=event("summary_unit_ready",unitPath);ready.addProperty("unit",1);ready.addProperty("total",2);view.acceptBatchStudyEvent(running,ready);});
            drainWorker();
            edt(()->{
                check(((Map<?,?>)get("liveSummarySections")).size()==1 && ((Map<?,?>)get("liveSummaryDrafts")).isEmpty(),"Queue ready unit did not settle the streamed draft");
                call("clearLiveSummary",new Class<?>[]{});
                view.observeBatchState(new PdfBatchQueue.Snapshot(2,source.id,source.name,running.storedPdf(),PdfBatchQueue.State.COMPLETE,100,"",0,"newest-k1-1-3"));
                check(!(boolean)get("externalBatchActive") && ((JButton)get("generate")).isEnabled(),"Completed queue left generation locked");
                // A local in-flight stream remains owned locally, even for the same engine/key.
                set("liveGenerationKey",PdfWorkspace.strategyProductKey("newest-k1-1-3","document",0));
                var next=new PdfBatchQueue.Snapshot(3,source.id,source.name,running.storedPdf(),PdfBatchQueue.State.RUNNING,30,"",0,"newest-k1-1-3");
                view.acceptBatchStudyEvent(next,event("summary_overview_ready",partial));
                check(((Long)get("liveBatchOrder"))==-1,"Queue attached itself to a local in-flight stream");
            });
            drainWorker();
            edt(()->check(get("liveOverview")==null,"Queue event overwrote a local in-flight stream"));
        }finally {if(view!=null)edt(()->view.close());else source.close();}
        System.out.println("NewestK1_1_3UiTest passed: one live overview card, retained progress/tutor notice, completion/reset, engine selection, queue ownership/guards, forwarded stream, stale-event isolation, local-run preservation");
        System.exit(0);
    }
}
