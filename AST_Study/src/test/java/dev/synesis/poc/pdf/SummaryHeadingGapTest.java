package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.awt.geom.Rectangle2D;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Structural headings stay together, without changing prose, anchors or saved JSON. No API/window. */
public final class SummaryHeadingGapTest {
    private static final Path OUT=Path.of("build/pdf-heading-gaps-20261022");
    public static void main(String[]args)throws Exception {
        boolean baseline=args.length>0&&args[0].equals("--before");String mode=baseline?"before":"after";
        JsonArray results=new JsonArray();
        SwingUtilities.invokeAndWait(()->{try(PdfWorkspace workspace=new PdfWorkspace(false,Files.createTempDirectory("heading-gap-"))) {
            Field skin=PdfWorkspace.class.getDeclaredField("summaryReadingSkin");skin.setAccessible(true);skin.set(workspace,true);
            Method hierarchy=PdfWorkspace.class.getDeclaredMethod("summaryHierarchy",List.class,String.class,Map.class);hierarchy.setAccessible(true);
            Method render=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);render.setAccessible(true);
            JPanel flow=(JPanel)get(workspace,"summaryFlow");JScrollPane scroll=(JScrollPane)get(workspace,"summaryScroll");
            List<SummaryOutline.Entry> fixture=fixture();checkCase(workspace,hierarchy,render,flow,scroll,fixture,"four-level",baseline,mode,results);
            for(String prefix:List.of("53b612601768","19ad29502917")) {
                Path library=Path.of("/Users/c4t/SYNESIS Data/library");Path source;
                try(var paths=Files.list(library)){source=paths.filter(p->p.getFileName().toString().startsWith(prefix)).findFirst().orElseThrow();}
                Path file=source.resolve("generated/new-concept-v99/latest-document-0.json");String saved=Files.readString(file);
                JsonObject result=JsonParser.parseString(saved).getAsJsonObject();List<SummaryOutline.Entry> entries=SummaryOutline.entries(result);
                entries=entries.subList(0,Math.min(prefix.startsWith("53")?3:4,entries.size()));
                checkCase(workspace,hierarchy,render,flow,scroll,entries,prefix.startsWith("53")?"matrix67":"sequences143",baseline,mode,results);
                check(Files.readString(file).equals(saved),"saved result changed");
            }
            check(fixture.get(4).content().size()==1,"ordinary parent body disappeared");
        }catch(Exception error){throw new RuntimeException(error);}});
        Files.writeString(OUT.resolve("gaps-"+mode+".json"),results.toString());
        System.out.println("PASS: "+mode+" heading geometry, real 67/143-page saved examples, four levels, narrow wrapping, body/TOC/citation preservation");System.exit(0);
    }
    private static void checkCase(PdfWorkspace w,Method hierarchy,Method render,JPanel flow,JScrollPane scroll,
                                  List<SummaryOutline.Entry> entries,String name,boolean baseline,String mode,JsonArray results)throws Exception {
        String unchanged=entries.toString();Map<String,SlideLens.Request> modules=new LinkedHashMap<>();
        String body=(String)hierarchy.invoke(w,entries,"gap-fixture",modules);
        for(int width:new int[]{800,340}) {
            render.invoke(w,body,modules);scroll.setSize(width,1000);scroll.doLayout();
            flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);layout(flow);scroll.getViewport().setViewSize(flow.getSize());
            Map<String,SummaryOutline.Target> targets=SummaryOutline.targets(flow);
            check(targets.keySet().equals(new LinkedHashSet<>(entries.stream().map(SummaryOutline.Entry::id).toList())),"outline anchors changed");
            for(int i=0;i+1<entries.size();i++) {
                SummaryOutline.Entry parent=entries.get(i),child=entries.get(i+1);
                if(!parent.content().isEmpty()||!child.parentId().equals(parent.id()))continue;
                Rectangle a=heading(flow,targets.get(parent.id()),parent.title(),true);
                Rectangle b=heading(flow,targets.get(child.id()),child.title(),false);
                int gap=b.y-(a.y+a.height);check(gap>=0,"headings overlap");
                if(!baseline)check(gap<=18,"heading-only parent leaves excessive gap: "+gap);
                JsonObject row=new JsonObject();row.addProperty("case",name);row.addProperty("width",width);row.addProperty("parent",parent.title());row.addProperty("child",child.title());row.addProperty("gapPx",gap);results.add(row);
            }
            if(!baseline&&name.equals("four-level")) {
                // A real explanation preserves its ordinary heading markup and
                // does not receive the heading-only parent style.
                check(body.contains(SummaryOutline.heading(entries.get(4))),"ordinary parent spacing was changed");
                check(text(flow).contains("본문이 있는 단원은 기존 간격을 유지해요."),"explanation lost");
            }
            check(entries.toString().equals(unchanged),"presentation mutated canonical entries");
            BufferedImage image=new BufferedImage(width,1000,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,width,1000);scroll.printAll(g);g.dispose();
            ImageIO.write(image,"png",OUT.resolve(name+"-"+width+"-"+mode+".png").toFile());
        }
    }
    private static Rectangle heading(JPanel flow,SummaryOutline.Target target,String title,boolean last)throws Exception {
        JEditorPane pane=target.pane();String text=pane.getDocument().getText(0,pane.getDocument().getLength());
        int start=text.indexOf(title,target.offset());check(start>=0,"heading text missing");
        Rectangle2D box=pane.modelToView2D(start+(last?title.length()-1:0));return SwingUtilities.convertRectangle(pane,box.getBounds(),flow);
    }
    private static List<SummaryOutline.Entry> fixture(){
        JsonObject part=new JsonObject();part.addProperty("body","본문이 있는 단원은 기존 간격을 유지해요.");
        return List.of(new SummaryOutline.Entry("a","","매우 긴 상위 단원의 제목이 여러 줄로 감겨도 간격을 유지해요",1,1,1,List.of()),
            new SummaryOutline.Entry("b","a","중간 제목",2,1,1,List.of()),
            new SummaryOutline.Entry("c","b","하위 제목",3,1,1,List.of()),
            new SummaryOutline.Entry("d","c","마지막 제목",4,1,1,List.of(part)),
            new SummaryOutline.Entry("body","","실제 설명이 있는 단원",1,2,2,List.of(part)),
            new SummaryOutline.Entry("body-child","body","다음 하위 항목",2,2,2,List.of(part)));
    }
    private static String text(Container c)throws Exception{StringBuilder out=new StringBuilder();for(Component child:c.getComponents())if(child instanceof JEditorPane p)out.append(p.getDocument().getText(0,p.getDocument().getLength()));else if(child instanceof Container nested)out.append(text(nested));return out.toString();}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static Object get(Object o,String name)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void check(boolean b,String reason){if(!b)throw new AssertionError(reason);}
}
