package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.tree.*;
import org.apache.pdfbox.pdmodel.*;

/** Offline body/TOC/anchor contract using the same metadata; no model calls. */
public final class SummaryOutlineTest {
    private static final Path OUT=Path.of("build/summary-hierarchy-test");
    private static PdfWorkspace workspace;
    private static JPanel flow;
    private static JScrollPane scroll;
    private static List<SummaryOutline.Entry> entries;
    private static JsonObject result;

    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);
        result=args.length>0?JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject():fixture();
        try {
            edt(SummaryOutlineTest::models);
            edt(SummaryOutlineTest::setup);flush();
            edt(()->{
                for(int width:new int[]{650,340}) {
                    layout(width);
                    Map<String,SummaryOutline.Target> anchors=SummaryOutline.targets(flow);
                    check(anchors.keySet().equals(new LinkedHashSet<>(entries.stream().map(SummaryOutline.Entry::id).toList())),"Body anchors and TOC differ");
                    String text=text(flow);
                    for(SummaryOutline.Entry entry:entries) {
                        check(text.contains(entry.title()),"Heading lost: "+entry.title());
                        for(JsonObject part:entry.content()) {
                            String body=part.get("body").getAsString().replaceAll("[*#]","").strip();
                            String start=body.split("[\\n$\\\\]",2)[0].strip();
                            if(start.length()>8)check(text.contains(start.substring(0,Math.min(18,start.length()))),"Prose lost: "+start);
                        }
                    }
                    snapshot("body-"+width+".png",flow,width,Math.min(1800,flow.getHeight()));
                    JTree tree=(JTree)get(workspace,"summaryOutlineTree");
                    tree.setSize(340,500);tree.doLayout();snapshot("toc.png",tree,340,500);
                }
                layout(650);
                @SuppressWarnings("unchecked") Map<String,TreePath> paths=(Map<String,TreePath>)get(workspace,"summaryOutlinePaths");
                for(SummaryOutline.Entry entry:entries) {
                    check(paths.containsKey(entry.id()),"Missing tree path");
                    Object user=((DefaultMutableTreeNode)paths.get(entry.id()).getLastPathComponent()).getUserObject();
                    check(user.equals(entry),"TOC changed the canonical entry");
                    call("activateSummaryOutline",new Class<?>[]{TreePath.class},paths.get(entry.id()));
                    SummaryOutline.Target target=SummaryOutline.targets(flow).get(entry.id());
                    int y=(Integer)call("summaryOutlineY",new Class<?>[]{SummaryOutline.Target.class},target);
                    int max=Math.max(0,flow.getHeight()-scroll.getViewport().getHeight());
                    check(Math.abs(scroll.getViewport().getViewPosition().y-Math.min(y,max))<=1,"TOC navigation missed heading");
                }
                check(!((JPopupMenu)get(workspace,"summaryOutlinePopup")).isVisible(),"TOC opened automatically");
                check(text(flow).contains("쉬운 설명"),"Existing easy explanations disappeared");
            });flush();
            edt(SummaryOutlineTest::partialAnchor);flush();
            edt(()->{
                @SuppressWarnings("unchecked") Map<String,SummaryOutline.Target> targets=SummaryOutline.targets(flow);
                int at=(Integer)call("summaryOutlineY",new Class<?>[]{SummaryOutline.Target.class},targets.get("later"));
                check(Math.abs(scroll.getViewport().getViewPosition().y-(at+20))<=2,"Earlier parallel unit moved the reader away from their heading");
            });
            System.out.println("SummaryOutlineTest passed: four levels, exact body/TOC tree, anchors, narrow layout, original preservation, orphan fallback and out-of-order reading position");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        finally {if(workspace!=null)edt(()->workspace.close());}
        System.exit(0);
    }
    private static void models() {
        String before=result.toString();entries=SummaryOutline.entries(result);
        check(!entries.isEmpty(),"Empty hierarchy");
        Set<String> seen=new HashSet<>();int actual=0;
        for(SummaryOutline.Entry entry:entries) {
            check(entry.level()>=1&&entry.level()<=4,"Unbounded hierarchy depth");
            check(entry.parentId().isEmpty()||seen.contains(entry.parentId()),"Child preceded parent");
            check(seen.add(entry.id()),"Duplicate node");
            check(SummaryOutline.heading(entry).contains("<h"+entry.level()+">"),"Heading level differs from TOC");
            actual+=entry.content().size();
        }
        int expected=0;for(JsonObject section:SummaryOutline.objects(result,"sections"))expected+=Math.max(1,SummaryOutline.objects(section,"parts").size());
        check(actual==expected,"Hierarchy omitted or duplicated prose");check(result.toString().equals(before),"Saved result mutated");
        List<String> expectedOrder=new ArrayList<>();
        for(JsonObject section:SummaryOutline.objects(result,"sections"))for(JsonObject part:SummaryOutline.objects(section,"parts"))
            expectedOrder.add(part.get("contentId").getAsString());
        check(entries.stream().flatMap(e->e.content().stream()).map(p->p.get("contentId").getAsString()).toList().equals(expectedOrder),
            "Body/TOC construction changed original part order");
        JsonObject legacy=result.deepCopy();legacy.remove("hierarchy");String old=legacy.toString();
        int count=SummaryOutline.entries(legacy).stream().mapToInt(e->e.content().size()).sum();
        check(count==expected&&legacy.toString().equals(old),"Legacy content changed");
        JsonObject orphan=fixture();orphan.getAsJsonObject("hierarchy").getAsJsonArray("nodes").get(3).getAsJsonObject().addProperty("parentId","missing");
        check(SummaryOutline.entries(orphan).stream().mapToInt(e->e.content().size()).sum()==2,"Orphan hierarchy hid prose");
        JsonObject early=unit("early",1),late=unit("late",9);
        JsonObject root=new JsonObject();root.addProperty("id","shared");root.addProperty("parentId","");root.addProperty("title","공통 단원");root.addProperty("page",1);
        for(JsonObject unit:List.of(early,late))unit.getAsJsonObject("hierarchy").getAsJsonArray("nodes").add(root);
        early.getAsJsonObject("hierarchy").getAsJsonArray("nodes").get(0).getAsJsonObject().addProperty("parentId","shared");
        late.getAsJsonArray("parts").get(0).getAsJsonObject().addProperty("nodeId","shared");
        check(SummaryOutline.live(List.of(early,late)).stream().flatMap(e->e.content().stream())
            .map(p->p.get("contentId").getAsString()).toList().equals(List.of("early","late")),
            "Later parallel parent explanation was moved above an earlier child");
    }
    private static void setup()throws Exception {
        Path file=OUT.resolve("empty.pdf");try(PDDocument pdf=new PDDocument()){pdf.addPage(new PDPage());pdf.save(file.toFile());}
        workspace=new PdfWorkspace(false,OUT.resolve("unused-library"));
        set(workspace,"source",PdfSource.open(file,OUT.resolve("unused-library")));
        set(workspace,"generated",result);set(workspace,"summaryReadingSkin",true);
        scroll=(JScrollPane)get(workspace,"summaryScroll");flow=(JPanel)get(workspace,"summaryFlow");
        call("renderSummary",new Class<?>[]{boolean.class},false);layout(650);
    }
    @SuppressWarnings("unchecked")
    private static void partialAnchor()throws Exception {
        String key=(String)call("productKey",new Class<?>[]{String.class,int.class},"document",0);set(workspace,"liveGenerationKey",key);
        Map<Integer,JsonObject> units=(Map<Integer,JsonObject>)get(workspace,"liveSummarySections");units.clear();
        JsonObject later=unit("later",2);units.put(2,later);call("renderLiveSummary",new Class<?>[]{});layout(650);
        int at=(Integer)call("summaryOutlineY",new Class<?>[]{SummaryOutline.Target.class},SummaryOutline.targets(flow).get("later"));
        scroll.getViewport().setViewPosition(new Point(0,at+20));
        units.put(1,unit("earlier",1));call("renderLiveSummary",new Class<?>[]{});layout(650);
    }
    private static JsonObject unit(String id,int page) {
        JsonObject unit=new JsonObject();unit.addProperty("title",id);unit.addProperty("body","본문");
        JsonObject part=new JsonObject();part.addProperty("title",id);part.addProperty("body",("원문 문맥을 유지하는 충분한 길이의 본문이에요.\n\n").repeat(45));part.addProperty("nodeId",id);part.addProperty("contentId",id);part.addProperty("easyExplanation","쉬운 설명이에요.");part.add("evidence",new JsonArray());
        JsonArray parts=new JsonArray();parts.add(part);unit.add("parts",parts);
        JsonObject node=new JsonObject();node.addProperty("id",id);node.addProperty("parentId","");node.addProperty("title",id);node.addProperty("level",1);node.addProperty("page",page);
        JsonArray nodes=new JsonArray();nodes.add(node);JsonObject hierarchy=new JsonObject();hierarchy.add("nodes",nodes);unit.add("hierarchy",hierarchy);return unit;
    }
    private static JsonObject fixture() {
        return JsonParser.parseString("""
          {"kind":"ai_generated","scope":"document","page":0,"strategy":"new-concept-v99",
           "overview":{"body":"전체 흐름을 설명해요."},"sections":[{"title":"원래 묶음","parts":[
             {"title":"손익계산서","body":"기업의 매출과 비용을 비교해요.\n\n$$A=B+C$$","easyExplanation":"가계부와 같아요.","nodeId":"income","contentId":"one"},
             {"title":"매출원가","body":"제품을 생산하는 직접 비용이에요.","easyExplanation":"재료비와 같아요.","nodeId":"cost","contentId":"two"}]}],
           "hierarchy":{"nodes":[
             {"id":"chapter","parentId":"","title":"6. 기업의 재무제표","level":1,"page":1},
             {"id":"income","parentId":"chapter","title":"6.1. 손익계산서","level":2,"page":1},
             {"id":"costs","parentId":"income","title":"기업의 네 가지 비용","level":3,"page":1},
             {"id":"cost","parentId":"costs","title":"매출원가","level":4,"page":1} ]}}
          """.replace("비교해요.\n\n$$","비교해요.\\n\\n$$")).getAsJsonObject();
    }
    private static void layout(int width) {
        scroll.getViewport().setExtentSize(new Dimension(width,650));scroll.getViewport().setSize(width,650);
        flow.setSize(width,Math.max(1,flow.getPreferredSize().height));flow.doLayout();nested(flow);
    }
    private static void nested(Container parent){for(Component c:parent.getComponents())if(c instanceof Container box&&!(c instanceof JEditorPane)){box.doLayout();nested(box);}}
    private static String text(Container parent)throws Exception {StringBuilder b=new StringBuilder();for(Component c:parent.getComponents())if(c instanceof JEditorPane pane)b.append(pane.getDocument().getText(0,pane.getDocument().getLength()));else if(c instanceof Container box)b.append(text(box));return b.toString();}
    private static void snapshot(String name,JComponent component,int width,int height)throws Exception {BufferedImage image=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,width,height);component.printAll(g);g.dispose();ImageIO.write(image,"png",OUT.resolve(name).toFile());}
    private static Object get(Object target,String name)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    private static Object call(String name,Class<?>[] types,Object...args)throws Exception {Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(workspace,args);}
    private static void edt(Throwing action)throws Exception {SwingUtilities.invokeAndWait(()->{try{action.run();}catch(Exception e){throw new RuntimeException(e);}});}
    private static void flush()throws Exception {edt(()->{});edt(()->{});}
    private interface Throwing{void run()throws Exception;}
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
