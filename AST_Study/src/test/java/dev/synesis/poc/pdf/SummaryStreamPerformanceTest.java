package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.awt.*;
import java.awt.event.ActionEvent;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;

/** Identical 14-unit UI event workload for before/after CPU measurements. No network or window. */
public final class SummaryStreamPerformanceTest {
    private static PdfWorkspace workspace;private static JPanel flow;private static JScrollPane scroll;private static int epoch;
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("stream-performance-");Path pdf=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<14;i++)doc.addPage(new PDPage());doc.save(pdf.toFile());}
        PdfSource source=PdfSource.open(pdf,root.resolve("library"));String[] bodies=new String[14];Arrays.fill(bodies,"학습 내용의 조건과 원리를 원문과 함께 살펴봐요. ".repeat(8));
        try {
            edt(()->{workspace=new PdfWorkspace(false,root.resolve("unused"));set("source",source);set("index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
                ((JComboBox<?>)get("summaryStrategy")).setSelectedIndex(7);call("clearLiveSummary");set("liveGenerationKey",call("productKey",new Class<?>[]{String.class,int.class},"document",0));
                epoch=((AtomicInteger)get("generation")).get();scroll=(JScrollPane)get("summaryScroll");flow=(JPanel)get("summaryFlow");
                call("setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.RUNNING);
                for(int unit=1;unit<=14;unit++)delta(unit,1,bodies[unit-1]);});edt(()->{flush();layout();});
            edt(()->{if(((Map<?,?>)get("liveSummaryDraftPanes")).size()!=14)throw new AssertionError("benchmark must apply all 14 streams before timing");});
            ArrayList<Double> times=new ArrayList<>();
            for(int round=0;round<30;round++){
                int sequence=round+2;for(int i=0;i<14;i++)bodies[i]+=" 새로운 설명이 도착하면서 기존 내용 뒤에 더해져요.";
                long[] ns={0},started={0};edt(()->{started[0]=System.nanoTime();for(int unit=1;unit<=14;unit++)delta(unit,sequence,bodies[unit-1]);});edt(()->{flush();layout();ns[0]=System.nanoTime()-started[0];});
                edt(()->{});if(round>=5)times.add(ns[0]/1e6);
            }
            times.sort(Double::compareTo);double sum=times.stream().mapToDouble(Double::doubleValue).sum();
            JsonObject row=new JsonObject();row.addProperty("units",14);row.addProperty("measuredUpdates",times.size());row.addProperty("meanUpdateMs",sum/times.size());row.addProperty("medianUpdateMs",times.get(times.size()/2));row.addProperty("p95UpdateMs",times.get((int)(times.size()*.95)));row.addProperty("newApiCalls",0);row.addProperty("nativeWindowsFpsMeasured",false);
            if(args.length>0){Path out=Path.of(args[0]);Files.createDirectories(out.getParent());Files.writeString(out,row.toString());}System.out.println(row);
        }finally{if(workspace!=null)edt(workspace::close);}
        System.exit(0);
    }
    private static void delta(int unit,int sequence,String body)throws Exception {
        JsonObject e=new JsonObject();e.addProperty("type","summary_unit_delta");e.addProperty("unit",unit);e.addProperty("total",14);e.addProperty("sequence",sequence);e.addProperty("scope","document");e.addProperty("selectionPage",0);e.addProperty("strategy","new-concept-v99");
        JsonObject summary=new JsonObject();summary.addProperty("title","생성 구간 "+unit);summary.addProperty("body",body);e.add("summary",summary);call("handleProgress",new Class<?>[]{int.class,JsonObject.class},epoch,e);
    }
    private static void flush()throws Exception {javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryDraftTimer");if(timer!=null&&timer.isRunning()){timer.stop();for(var listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,0,"fixture"));}}
    private static void layout(){scroll.setSize(646,500);scroll.doLayout();flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);flow.doLayout();for(Component child:flow.getComponents())if(child instanceof Container nested)nested.doLayout();scroll.getViewport().setViewSize(flow.getSize());}
    private static Object get(String name)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(workspace);}
    private static void set(String name,Object value)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(workspace,value);}
    private static Object call(String name)throws Exception{return call(name,new Class<?>[]{});}
    private static Object call(String name,Class<?>[]types,Object...values)throws Exception{Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(workspace,values);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work work)throws Exception{SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception error){throw new RuntimeException(error);}});}
}
