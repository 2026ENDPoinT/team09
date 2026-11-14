package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Saved rich overview: ordinary paint, transparent descendants, fade and scroll. */
public final class SummarySavedPaintTest {
    static Object field(Object o,String n)throws Exception {Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    static void check(boolean b,String why){if(!b)throw new AssertionError(why);}
    static void layout(Container c){c.doLayout();for(Component x:c.getComponents())if(x instanceof Container n)layout(n);}
    static BufferedImage paint(JComponent c,boolean printing){
        BufferedImage b=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=b.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,b.getWidth(),b.getHeight());
        if(printing)c.printAll(g);else c.paint(g);g.dispose();return b;
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try(PdfWorkspace w=new PdfWorkspace(false,Files.createTempDirectory("saved-summary-paint"))) {
            Method render=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);render.setAccessible(true);
            JScrollPane scroll=(JScrollPane)field(w,"summaryScroll");JPanel flow=(JPanel)field(w,"summaryFlow");
            SummaryOverviewLoading card=(SummaryOverviewLoading)field(w,"summaryOverviewLoading");
            JFrame host=null;
            if(args.length==1){host=new JFrame();host.setAutoRequestFocus(false);host.setLocation(-16000,-16000);host.setContentPane(scroll);host.setSize(800,500);host.setVisible(true);}
            String overview="<!--OVERVIEWSTART--><p>근대 예술의 사회적 관계와 르네상스 고전 미학에서 출발해 낭만주의와 사실주의를 거쳐 인상주의를 살펴봐요.</p><p>근거 <a href='page:4'>p.4</a> · p.14</p><!--OVERVIEWEND-->";
            if(args.length==2) {
                Path library=Path.of(args[0]);
                for(String key:new String[]{"index","generated","source"}) {
                    Field f=PdfWorkspace.class.getDeclaredField(key);f.setAccessible(true);
                    f.set(w,key.equals("source")?PdfSource.open(library.resolve("source.pdf"),Files.createTempDirectory("saved-paint-source")):
                        com.google.gson.JsonParser.parseString(Files.readString(key.equals("index")?library.resolve("document.json"):Path.of(args[1]))).getAsJsonObject());
                }
            }
            String body=overview+"<h2>근대 예술의 장과 사회적 관계</h2><p>"+"기존에 저장된 본문과 근거를 유지해요. ".repeat(80)+"</p>";
            Path out=Path.of("build/pdf-saved-render-fix-20261021");Files.createDirectories(out);
            for(int width:new int[]{800,646,340,800}) {
                // Reopening a saved result repeatedly reuses the card and panes.
                if(args.length==2) {
                    Method saved=PdfWorkspace.class.getDeclaredMethod("renderSummary");saved.setAccessible(true);saved.invoke(w);
                } else render.invoke(w,body,Map.of());
                scroll.setSize(width,500);scroll.doLayout();
                flow.setSize(scroll.getViewport().getWidth(),flow.getPreferredSize().height);layout(flow);
                scroll.getViewport().setViewSize(flow.getSize());scroll.doLayout();
                if(!flow.isDisplayable())flow.addNotify();
                RepaintManager.currentManager(flow).setDoubleBufferingEnabled(true);
                check(card.completed()&&card.completionFraction()==1,"saved result incorrectly animated as running");
                check(card.getHeight()>100,"saved overview collapsed");
                BufferedImage ordinary=paint(flow,false),printed=paint(flow,true);
                // Direct child.paint() reenters Swing buffering; its output must match
                // Swing's correctly traversed printing path, including transparent prose.
                int differences=0;
                for(int y=0;y<ordinary.getHeight();y++)for(int x=0;x<ordinary.getWidth();x++)
                    if(ordinary.getRGB(x,y)!=printed.getRGB(x,y))differences++;
                check(differences==0,"screen paint duplicates/clips transparent overview: "+differences+" pixels");
                ImageIO.write(ordinary,"png",out.resolve("saved-"+width+".png").toFile());
                @SuppressWarnings("unchecked") JLayer<JScrollPane> layer=(JLayer<JScrollPane>)field(w,"summaryFadeLayer");
                layer.setSize(width,500);layout(layer);
                Field alpha=PdfWorkspace.class.getDeclaredField("summaryFadeAlpha");alpha.setAccessible(true);alpha.set(w,.5f);
                paint(layer,false);alpha.set(w,0f);paint(layer,false);
                scroll.getViewport().setViewPosition(new Point(0,100));paint(scroll,false);
            }
            if(host!=null)host.dispose();
            System.out.println("PASS: saved overview repeated load, screen/print pixels, fade, resize and scroll");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.exit(0);
    }
}
