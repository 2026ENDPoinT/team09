package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.concurrent.atomic.*;

/** Real UI event handling, isolated storage, no API or native windows. */
public final class PdfPlanningProgressTest {
    static PdfWorkspace workspace;
    static Method handler,setProgress;
    static int epoch;
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planning-progress-");
        String previous=System.getProperty("synesis.dataRoot");System.setProperty("synesis.dataRoot",root.toString());
        try {
            SwingUtilities.invokeAndWait(()->{try {
                workspace=new PdfWorkspace(false,root.resolve("library"));
                handler=PdfWorkspace.class.getDeclaredMethod("handleProgress",int.class,JsonObject.class);handler.setAccessible(true);
                setProgress=PdfWorkspace.class.getDeclaredMethod("setGenerationProgress",PdfWorkspace.GenerationProgress.class);setProgress.setAccessible(true);
                epoch=((AtomicInteger)get("generation")).get();reset();
            }catch(Exception e){throw new RuntimeException(e);}});
            event("split_start",3,null,null);check(3,"preparation did not move off zero");
            event("split_done",10,null,null);check(10,"local preparation was not reflected");
            event("group_start",11,null,null);check(11,"planning start was not reflected");
            event("group_progress",15,1,2);check(15,"completed planning window was not reflected");
            SwingUtilities.invokeAndWait(()->{try {if(!((JLabel)get("status")).getText().contains("1/2구간 완료"))throw new AssertionError("real completed-window count missing");}catch(Exception e){throw new RuntimeException(e);}});
            event("group_done",20,null,null);check(20,"confirmed planning did not finish at twenty");
            // The second worker prepares its source again using the local cache.
            // Replayed setup events must not undo either the bar or its stage.
            event("split_start",3,null,null);event("split_done",10,null,null);event("group_start",11,null,null);
            check(20,"the group-plan to generate handoff regressed");
            SwingUtilities.invokeAndWait(()->{try {if(!((JLabel)get("status")).getText().contains("의미 단위"))throw new AssertionError("stage text went backwards");}catch(Exception e){throw new RuntimeException(e);}});
            event("units_ready",20,null,null);event("unit_done",60,null,null);check(60,"body progress stopped updating");
            SwingUtilities.invokeAndWait(()->{try {((AtomicInteger)get("generation")).incrementAndGet();}catch(Exception e){throw new RuntimeException(e);}});
            event("group_progress",19,2,2);check(60,"stale event changed the new generation");
            SwingUtilities.invokeAndWait(()->{try {reset();}catch(Exception e){throw new RuntimeException(e);}});check(0,"new run could not reset");
            System.out.println("PASS: actual planning counts update both bars/stages; phase handoff is monotonic; stale events ignored; new run resets");
        } finally {
            if(workspace!=null)SwingUtilities.invokeAndWait(workspace::close);
            if(previous==null)System.clearProperty("synesis.dataRoot");else System.setProperty("synesis.dataRoot",previous);
        }
        System.exit(0);
    }
    static void reset()throws Exception {setProgress.invoke(workspace,new PdfWorkspace.GenerationProgress("fixture","fixture.pdf",0,"준비 중",false,false));}
    static void event(String stage,int percent,Integer done,Integer total)throws Exception {
        JsonObject e=new JsonObject();e.addProperty("type","study_timeline");e.addProperty("stage",stage);e.addProperty("percent",percent);
        if(done!=null){e.addProperty("completedWindows",done);e.addProperty("totalWindows",total);}
        handler.invoke(workspace,epoch,e);SwingUtilities.invokeAndWait(()->{});
    }
    static void check(int expected,String message)throws Exception {SwingUtilities.invokeAndWait(()->{try {if(((SummaryActivityBar)get("summaryActivity")).progress()!=expected)throw new AssertionError(message);}catch(Exception e){throw new RuntimeException(e);}});}
    static Object get(String name)throws Exception {Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(workspace);}
}
