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

/** Python-emitted SSE preview events enter the real Java progress handler; no API/window. */
public final class SummaryStreamReplayTest {
    private static PdfWorkspace workspace;
    private static PdfSource source;
    private static JPanel flow;
    private static JScrollPane scroll;
    private static int epoch;
    private static final Path OUT=Path.of("build/pdf-live-stream-20261021");
    public static void main(String[] args)throws Exception {
        Path artifact=args.length>0?Path.of(args[0]):OUT.resolve("stream-replay.json");
        JsonObject replay=JsonParser.parseString(Files.readString(artifact)).getAsJsonObject();
        String retained=replay.toString();
        Map<Integer,JsonObject> originals=new TreeMap<>();
        for(JsonElement value:replay.getAsJsonArray("units")) {
            JsonObject row=value.getAsJsonObject();originals.put(row.get("unit").getAsInt(),row.getAsJsonObject("value").deepCopy());
        }
        check(!originals.isEmpty(),"replay has no canonical unit fixtures");
        Path root=Files.createTempDirectory("summary-real-event-replay-");Path input=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<33;i++)doc.addPage(new PDPage());doc.save(input.toFile());}
        source=PdfSource.open(input,root.resolve("library"));
        Map<Integer,Path> files=new TreeMap<>();
        for(var row:originals.entrySet()) {
            Path path=source.folder.resolve("generated/new-concept-v99/replay").resolve(String.format(Locale.ROOT,"unit-%05d.json",row.getKey()-1));
            Files.createDirectories(path.getParent());Files.writeString(path,row.getValue().toString());files.put(row.getKey(),path);
        }
        try {
            edt(()->{
                workspace=new PdfWorkspace(false,root.resolve("unused"));set("source",source);
                set("index",JsonParser.parseString("{\"pages\":[],\"chunks\":[]}").getAsJsonObject());
                ((JComboBox<?>)get("summaryStrategy")).setSelectedIndex(7);
                call("clearLiveSummary");set("liveGenerationKey",call("productKey",new Class<?>[]{String.class,int.class},"document",0));
                epoch=((AtomicInteger)get("generation")).get();scroll=(JScrollPane)get("summaryScroll");flow=(JPanel)get("summaryFlow");
                call("setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.RUNNING);layout();
            });drain();
            boolean partialVisible=false;int readyCount=0,deltaCount=0;
            for(JsonElement item:replay.getAsJsonArray("events")) {
                JsonObject event=item.getAsJsonObject().deepCopy();String type=event.get("type").getAsString();
                if(type.equals("summary_unit_ready")) {
                    int unit=event.get("unit").getAsInt();event.addProperty("path",files.get(unit).toString());readyCount++;
                }
                call("handleProgress",new Class<?>[]{int.class,JsonObject.class},epoch,event);drain();frame();
                if(type.equals("summary_unit_delta")&&(!event.has("discard")||!event.get("discard").getAsBoolean())) {
                    deltaCount++;String body=event.getAsJsonObject("summary").get("body").getAsString();
                    if(readyCount==0 && !body.isBlank()) {
                        check(event.has("beforeTerminal")&&event.get("beforeTerminal").getAsBoolean(),"preview emitted only after terminal response");
                        final String previewBody=body;edt(()->{
                            String actual=plain(text(flow));boolean learnerParagraph=false;
                            for(String paragraph:previewBody.split("\n\n",-1)) {
                                // A matching first heading is intentionally rendered
                                // once by the outer native heading, beside its page label.
                                if(paragraph.isBlank()||paragraph.matches("#{1,6} [^\n]+"))continue;
                                learnerParagraph=true;
                                check(actual.contains(plain(paragraph)),"real emitted learner paragraph not visible before canonical unit-ready");
                            }
                            check(learnerParagraph,"real replay did not contain learner prose");
                        });
                        if(!partialVisible){edt(()->snapshot("stream-replay-midstream.png"));partialVisible=true;}
                    }
                }
                if(type.equals("summary_unit_ready")) {
                    int unit=event.get("unit").getAsInt();
                    edt(()->{
                        check(!map("liveSummaryDrafts").containsKey(unit),"canonical unit retained duplicate draft");
                        JsonObject summary=(JsonObject)map("liveSummarySections").get(unit);
                        check(summary.equals(originals.get(unit).getAsJsonObject("summary")),"canonical text/math/source content changed after stream replacement");
                    });
                }
            }
            check(partialVisible&&deltaCount>0,"replay did not contain real pre-terminal previews");
            check(readyCount==originals.size(),"some canonical fixtures did not receive ready events");
            edt(()->{
                check(map("liveSummaryDrafts").isEmpty(),"draft remained after all canonical units arrived");
                check(map("liveSummarySections").size()==originals.size(),"canonical unit replay duplicated/lost content");
                check(map("products").isEmpty()&&get("generated")==null,"live-only metadata entered export/products");
                for(Object value:map("liveSummarySections").values())check(!value.toString().contains("_liveSummaryUnit"),"draft rendering marker contaminated canonical source");
                // Build a local final presentation from the exact validated units;
                // the synthetic overview is only a test fixture, never persisted.
                JsonObject result=finalResult(originals);call("clearLiveSummary");set("generated",result);
                call("setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.IDLE);
                call("renderSummary",new Class<?>[]{boolean.class},false);layout();snapshot("stream-replay-completed.png");
                check(!result.toString().contains("_liveSummaryUnit"),"final presentation contains streaming markers");
            });
            for(var row:files.entrySet())check(JsonParser.parseString(Files.readString(row.getValue())).equals(originals.get(row.getKey())),"display changed a canonical unit file");
            check(replay.toString().equals(retained),"event replay input was mutated");
            check(!Files.exists(source.folder.resolve("requests")),"replay launched a model request");
            System.out.println("PASS: Python SSE events visibly stream before unit-ready; exact canonical math/text replacement, no draft export pollution; "+deltaCount+" deltas / "+readyCount+" units");
        }catch(Throwable failure){failure.printStackTrace();System.exit(1);}
        finally {if(workspace!=null)edt(workspace::close);}
        System.exit(0);
    }
    private static JsonObject finalResult(Map<Integer,JsonObject> originals) {
        JsonObject result=new JsonObject();result.addProperty("kind","ai_generated");result.addProperty("scope","document");result.addProperty("page",0);result.addProperty("strategy","new-concept-v99");
        JsonArray sections=new JsonArray(),concepts=new JsonArray();for(JsonObject unit:originals.values()){sections.add(unit.getAsJsonObject("summary").deepCopy());for(JsonElement concept:unit.getAsJsonArray("concepts"))concepts.add(concept.deepCopy());}
        result.add("sections",sections);result.add("concepts",concepts);
        JsonObject overview=new JsonObject();overview.addProperty("title","이 강의의 흐름");overview.addProperty("body","스트림으로 받은 학습 단위의 설명과 수식을 정리했어요.");overview.addProperty("easyExplanation","");overview.add("evidence",new JsonArray());overview.add("visualPages",new JsonArray());overview.addProperty("standardKnowledgeUsed",false);result.add("overview",overview);return result;
    }
    private static void frame()throws Exception {edt(()->{
        javax.swing.Timer timer=(javax.swing.Timer)get("liveSummaryDraftTimer");
        if(timer!=null&&timer.isRunning()){timer.stop();for(var listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,ActionEvent.ACTION_PERFORMED,"replay frame"));}
        layout();
    });drain();}
    private static void snapshot(String file)throws Exception {
        Files.createDirectories(OUT);layout();scroll.getViewport().setViewPosition(new Point(0,0));BufferedImage image=new BufferedImage(scroll.getWidth(),scroll.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());scroll.printAll(g);g.dispose();ImageIO.write(image,"png",OUT.resolve(file).toFile());
    }
    private static void layout(){scroll.setSize(800,650);scroll.doLayout();flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);layoutChildren(flow);scroll.getViewport().setViewSize(flow.getSize());scroll.doLayout();}
    private static void layoutChildren(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layoutChildren(nested);}
    private static String text(Container c)throws Exception {StringBuilder value=new StringBuilder();for(Component child:c.getComponents())if(child.isVisible()){if(child instanceof JEditorPane pane)value.append(pane.getDocument().getText(0,pane.getDocument().getLength()));else if(child instanceof Container nested)value.append(text(nested));}return value.toString();}
    private static Map<?,?> map(String name)throws Exception{return (Map<?,?>)get(name);}
    private static Object get(String name)throws Exception{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field.get(workspace);}
    private static void set(String name,Object value)throws Exception{Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);field.set(workspace,value);}
    private static Object call(String name)throws Exception{return call(name,new Class<?>[]{});}
    private static Object call(String name,Class<?>[] types,Object...values)throws Exception{Method method=PdfWorkspace.class.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(workspace,values);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work action)throws Exception{SwingUtilities.invokeAndWait(()->{try{action.run();}catch(Exception error){throw new RuntimeException(error);}});}
    private static void drain()throws Exception{edt(()->{});edt(()->{});}
    private static String plain(String value){return value.replace("\u001c","").replace("\u001d","").replaceAll("(?m)^#{1,6} ","").replaceAll("\\s+"," ").strip();}
    private static void check(boolean condition,String why){if(!condition)throw new AssertionError(why);}
}
