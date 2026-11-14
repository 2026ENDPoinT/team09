package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Offline: background drafts retain all text without layout; orb frames damage only moving pixels. */
public final class GenerationViewCpuTest {
    private static PdfWorkspace view;
    private static JsonObject metrics=new JsonObject();
    private static boolean baseline;
    public static void main(String[] args)throws Exception {
        baseline=Arrays.asList(args).contains("--baseline");
        Path root=Files.createTempDirectory("synesis-generation-cpu-");Path pdf=root.resolve("fixture.pdf");
        try(PDDocument document=new PDDocument()){document.addPage(new PDPage());document.save(pdf.toFile());}
        PdfSource source=PdfSource.open(pdf,root.resolve("library"));
        try {
            edt(()->{
                view=new PdfWorkspace(false,root.resolve("unused"));set(view,"source",source);
                set(view,"index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
                set(view,"liveGenerationKey",call(view,"productKey",new Class<?>[]{String.class,int.class},"document",0));
                view.setSize(1200,800);view.addNotify();view.setVisible(false);view.removeNotify();
                Map<Integer,JsonObject> drafts=map(view,"liveSummaryDrafts");
                long start=ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime();
                for(int round=0;round<30;round++) {
                    for(int unit=1;unit<=14;unit++) {
                        JsonObject draft=new JsonObject();draft.addProperty("title","생성 구간 "+unit);
                        draft.addProperty("body","원문과 설명을 함께 보존해요. ".repeat(20+round));drafts.put(unit,draft);
                    }
                    call(view,"refreshStreamingSummaryPanes",new Class<?>[]{});
                }
                metrics.addProperty("hiddenUpdates",30);metrics.addProperty("hiddenCpuMs",(ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime()-start)/1e6);
                int panes=map(view,"liveSummaryDraftPanes").size();metrics.addProperty("hiddenDraftPanes",panes);
                if(!baseline)check(panes==0,"hidden generation laid out draft documents");
                check(drafts.size()==14,"hidden updates lost units");
                for(JsonObject draft:drafts.values())check(draft.get("body").getAsString().equals("원문과 설명을 함께 보존해요. ".repeat(49)),"latest hidden text was lost");
                view.addNotify();view.setVisible(true);
            });
            edt(()->{
                check(map(view,"liveSummaryDraftPanes").size()==14,"returning to summary did not refresh all drafts");
                for(Object pane:map(view,"liveSummaryDraftPanes").values()) {
                    JEditorPane text=(JEditorPane)pane;
                    check(text.getDocument().getText(0,text.getDocument().getLength()).contains("원문과 설명을 함께 보존해요."),"resumed view lost learner text");
                }
                if(!baseline) {
                    view.setVisible(false);map(view,"liveSummaryDrafts").clear();
                    JsonObject canonical=new JsonObject();canonical.addProperty("title","완료된 해설");canonical.addProperty("body","완료된 수식 $x^2$와 원문을 보존해요.");
                    String original=canonical.toString();map(view,"liveSummarySections").put(1,canonical);map(view,"liveSummaryVisible").put(1,0);
                    int[] completed={0};set(view,"liveSummaryCompletion",(Runnable)()->completed[0]++);
                    call(view,"advanceLiveSummary",new Class<?>[]{});
                    check(completed[0]==1,"hidden typing kept completed generation busy");
                    check(canonical.toString().equals(original),"hidden completion changed canonical result");
                    call(view,"showConcepts",new Class<?>[]{boolean.class},true);
                    check((boolean)get(view,"conceptRenderPending"),"hidden concept refresh was not deferred");
                    check(map(view,"conceptCards").isEmpty(),"hidden concepts built rich cards");
                }
                HomeAssistant home=new HomeAssistant();RepaintManager previous=RepaintManager.currentManager(home);
                try {
                    home.setSize(1200,800);home.doLayout();set(home,"loaded",true);
                    for(int i=0;i<4;i++)call(home,"animate",new Class<?>[]{});
                    JComponent orb=(JComponent)get(home,"orb");
                    long[] pixels={0};int[] frames={0};
                    RepaintManager.setCurrentManager(new RepaintManager(){
                        @Override public void addDirtyRegion(JComponent c,int x,int y,int width,int height){
                            if(c==orb){pixels[0]+=(long)width*height;frames[0]++;}
                        }
                    });
                    for(int i=0;i<120;i++)call(home,"animate",new Class<?>[]{});
                    metrics.addProperty("orbFrames",frames[0]);metrics.addProperty("orbDirtyPixels",pixels[0]);
                    if(!baseline)check(pixels[0]<=120L*9000,"idle orb repaints its wide hint area");
                }finally{RepaintManager.setCurrentManager(previous);home.close();}
            });
            Path output=Path.of(args[0]);Files.createDirectories(output.getParent());Files.writeString(output,metrics.toString());System.out.println(metrics);
        }finally{if(view!=null)edt(()->{view.close();view.removeNotify();});}
        System.exit(0);
    }
    @SuppressWarnings("unchecked") private static <T> Map<Integer,T> map(Object target,String name)throws Exception{return (Map<Integer,T>)get(target,name);}
    private static Object get(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void set(Object target,String name,Object value)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    private static Object call(Object target,String name,Class<?>[] types,Object... values)throws Exception{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,values);}
    private static void check(boolean condition,String why){if(!condition)throw new AssertionError(why);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work work)throws Exception{SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception e){throw new RuntimeException(e);}});}
}
