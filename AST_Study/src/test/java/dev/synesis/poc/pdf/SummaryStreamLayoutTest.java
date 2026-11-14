package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.awt.*;
import java.awt.event.ActionEvent;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Real summary hierarchy: units 1/3/10, append, canonical replacement and later unit 2. */
public final class SummaryStreamLayoutTest {
    private static PdfWorkspace workspace;private static PdfSource source;private static JPanel flow;private static JScrollPane scroll;private static int epoch,y3,n1;private static Path savedFile;private static String savedContent;
    public static void main(String[]args)throws Exception {
        Path root=Files.createTempDirectory("stream-layout-");Path input=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<10;i++)doc.addPage(new PDPage());doc.save(input.toFile());}
        source=PdfSource.open(input,root.resolve("library"));
        try {
            edt(()->{
                workspace=new PdfWorkspace(false,root.resolve("unused"));set("source",source);set("index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
                ((JComboBox<?>)get("summaryStrategy")).setSelectedIndex(7);call("clearLiveSummary");set("liveGenerationKey",call("productKey",new Class<?>[]{String.class,int.class},"document",0));
                epoch=((AtomicInteger)get("generation")).get();flow=(JPanel)get("summaryFlow");scroll=(JScrollPane)get("summaryScroll");
                call("setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.RUNNING);
                delta(1,1,"이 구간의 설명이 도착하는 대로 표시돼요. ".repeat(4));delta(3,1,"다음 구간은 원문의 조건과 개념을 설명해요.");delta(10,1,"마지막 구간도 도착하는 대로 자리 잡아요.");
            });edt(()->{flush();layout();settle();layout();
                check(spaces().keySet().equals(new TreeSet<>(java.util.List.of(1,3,10))),"unit-owned spaces are missing or incorrectly numbered");
                check(spaces().get(1).height()>0&&spaces().get(3).height()>0,"active units did not reserve spare room");
                snapshot("sections-1-3-10.png");
                y3=pane(3).getY();n1=pane(1).getHeight();
                String first="이 구간의 설명이 도착하는 대로 표시돼요. ".repeat(4);
                delta(1,2,first+"새로운 설명 ".repeat(12));
            });edt(()->{flush();layout();
                check(pane(1).getHeight()>n1,"fixture did not force a real wrapped line");
                check(pane(3).getY()==y3,"wrapping moved unit 3: "+y3+" -> "+pane(3).getY()+", unit1 "+n1+" -> "+pane(1).getHeight()+", spacer "+spaces().get(1).height()+", footprint "+spaces().get(1).footprint());
                JsonObject unit=canonical();String retained=unit.toString();Path file=source.folder.resolve("generated/new-concept-v99/motion/unit-00000.json");Files.createDirectories(file.getParent());Files.writeString(file,retained);savedFile=file;savedContent=retained;
                JsonObject ready=new JsonObject();ready.addProperty("type","summary_unit_ready");ready.addProperty("unit",1);ready.addProperty("total",10);ready.addProperty("scope","document");ready.addProperty("selectionPage",0);ready.addProperty("path",file.toString());deliver(ready);
            });edt(()->{flushReady();flush();layout();settle();layout();
                check(spaces().get(1).height()>0,"complete unit 1 discarded its reservation while unit 2 is missing");
                check(!getMap("liveSummarySections").get(1).toString().contains("_liveSummarySpace"),"layout-only metadata polluted canonical teaching");
                delta(2,1,"구간 2의 설명이 도착했어요. 앞 구간의 여유 공백을 정리해요.");
            });edt(()->{flush();layout();settle();layout();
                check(spaces().get(1).height()==0,"adjacent unit 2 left an unnecessary gap after complete unit 1");
                check(spaces().get(2).height()>0,"new streaming unit 2 lacks its own spare room");
                snapshot("section-2-arrived.png");
                AtomicInteger completions=new AtomicInteger();set("liveSummaryCompletion",(Runnable)completions::incrementAndGet);
                call("finishLiveSummaryMotion");call("completeLiveSummaryIfReady");
                check(completions.get()==1,"offscreen completion waited for an invisible animation");
                call("completeLiveSummaryIfReady");check(completions.get()==1,"completion ran more than once");
                check(spaces().values().stream().allMatch(s->s.height()==0&&!s.moving()),"final result retained live reservations");
                check(Files.readString(savedFile).equals(savedContent),"presentation modified the canonical unit file");
                call("clearLiveSummary");check(spaces().isEmpty(),"cancel/final cleanup leaked reservations");
                javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryMotionTimer");check(timer==null||!timer.isRunning(),"cleanup left a motion timer running");
                check(!Files.exists(source.folder.resolve("requests")),"layout test launched an API request");
            });
        }finally{if(workspace!=null)edt(workspace::close);}
        System.out.println("PASS: real 1/3/10 hierarchy, stable following unit on wrap, retained missing-unit gap, adjacent unit 2 release, exact saved content, cleanup");System.exit(0);
    }
    @SuppressWarnings("unchecked")private static Map<Integer,SummaryStreamSpace>spaces()throws Exception{return (Map<Integer,SummaryStreamSpace>)get("liveSummarySpaces");}
    private static Map<?,?>getMap(String name)throws Exception{return (Map<?,?>)get(name);}
    private static JEditorPane pane(int unit)throws Exception{return (JEditorPane)getMap("liveSummaryDraftPanes").get(unit);}
    private static void settle()throws Exception{spaces().values().forEach(SummaryStreamSpace::settle);}
    private static void delta(int number,int sequence,String body)throws Exception {
        JsonObject event=new JsonObject();event.addProperty("type","summary_unit_delta");event.addProperty("unit",number);event.addProperty("total",10);event.addProperty("sequence",sequence);event.addProperty("scope","document");event.addProperty("selectionPage",0);event.addProperty("strategy","new-concept-v99");
        JsonObject summary=new JsonObject();summary.addProperty("title","구간 "+number);summary.addProperty("body",body);JsonArray pages=new JsonArray();pages.add(number);summary.add("visualPages",pages);event.add("summary",summary);deliver(event);
    }
    private static void deliver(JsonObject event)throws Exception{call("handleProgress",new Class<?>[]{int.class,JsonObject.class},epoch,event);}
    private static JsonObject canonical(){return JsonParser.parseString("""
        {"summary":{"title":"구간 1","body":"원문과 근거를 확인한 첫 구간의 설명이에요.","parts":[{"nodeId":"one","contentId":"one/body","title":"구간 1","body":"원문과 근거를 확인한 첫 구간의 설명이에요.","visualPages":[1],"evidence":[]}],"hierarchy":{"nodes":[{"id":"one","parentId":"","title":"구간 1","page":1,"level":1}]},"visualPages":[1],"evidence":[]},"concepts":[]}
        """).getAsJsonObject();}
    private static void flushReady()throws Exception {javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryRefreshTimer");if(timer!=null&&timer.isRunning()){timer.stop();for(var listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,0,"fixture"));}}
    private static void flush()throws Exception {javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryDraftTimer");if(timer!=null&&timer.isRunning()){timer.stop();for(var listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,0,"fixture"));}}
    private static void layout(){scroll.setSize(800,1050);scroll.doLayout();flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);flow.doLayout();for(Component child:flow.getComponents())if(child instanceof Container nested)nested.doLayout();scroll.getViewport().setViewSize(flow.getSize());}
    private static void snapshot(String name)throws Exception{BufferedImage image=new BufferedImage(800,1050,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,800,1050);scroll.printAll(g);g.dispose();ImageIO.write(image,"png",Path.of("build/pdf-stream-motion-20261022",name).toFile());}
    private static Object get(String name)throws Exception{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field.get(workspace);}
    private static void set(String name,Object value)throws Exception{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);field.set(workspace,value);}
    private static Object call(String name)throws Exception{return call(name,new Class<?>[]{});}
    private static Object call(String name,Class<?>[]types,Object...args)throws Exception{Method method=PdfWorkspace.class.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(workspace,args);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work work)throws Exception{SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception error){throw new RuntimeException(error);}});}
    private static void check(boolean condition,String why){if(!condition)throw new AssertionError(why);}
}
