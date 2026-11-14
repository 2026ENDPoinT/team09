package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.FadeScrollPane;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.List;
import java.util.function.Consumer;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Offline geometry and pixel checks for vector equations and shared edge hints. */
public final class HorizontalOverflowTest {
    private static final String MATH="$$\\int_{2}^{17/5}\\frac{dx}{\\sqrt{25x^2-64}}="
        +"\\left[\\frac{1}{5}\\ln\\left(5x+\\sqrt{25x^2-64}\\right)\\right]_{2}^{17/5}$$";
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try { edges();bubble(); } catch(Exception e) {throw new RuntimeException(e);}
        });
        System.out.println("HorizontalOverflowTest passed");System.exit(0);
    }
    private static void edges() {
        JComponent content=new JComponent() {
            @Override protected void paintComponent(Graphics g) {
                g.setColor(new Color(40,40,40));g.fillRect(0,0,getWidth(),getHeight());
            }
        };
        content.setOpaque(true);content.setBackground(Color.WHITE);content.setPreferredSize(new Dimension(900,70));
        JScrollPane scroll=new FadeScrollPane(content);scroll.setBorder(null);scroll.setSize(250,100);
        scroll.doLayout();scroll.getViewport().doLayout();
        JViewport viewport=scroll.getViewport();
        int max=viewport.getViewSize().width-viewport.getWidth();
        require(max>0,"fixture overflows");
        checkEdges(viewport,0,false,true);
        checkEdges(viewport,max/2,true,true);
        checkEdges(viewport,max,true,false);
        content.setPreferredSize(new Dimension(100,70));content.setSize(100,70);
        viewport.setViewPosition(new Point(0,0));viewport.doLayout();
        checkEdges(viewport,0,false,false);
    }
    private static void checkEdges(JViewport viewport,int x,boolean left,boolean right) {
        viewport.setViewPosition(new Point(x,0));
        BufferedImage image=new BufferedImage(viewport.getWidth(),viewport.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();viewport.paint(g);g.dispose();
        require((new Color(image.getRGB(2,20)).getRed()>65)==left,"left hint at "+x);
        require((new Color(image.getRGB(image.getWidth()-3,20)).getRed()>65)==right,"right hint at "+x);
    }
    private static void bubble() throws Exception {
        int font=24,width=287;
        Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$RoundedTutorBubble");
        Constructor<?> constructor=type.getDeclaredConstructor(String.class,boolean.class,int.class,int.class,Consumer.class,List.class);
        constructor.setAccessible(true);
        String rendered=StudyMarkdown.renderWithScrollableMath("적분값이에요.\n\n"+MATH+"\n\n마지막 설명이에요.",font,true,width-24);
        require(rendered.contains("MATHSCROLL:"),"narrow tutor extracts long equation");
        JPanel bubble=(JPanel)constructor.newInstance(rendered,false,width,font,(Consumer<String>)s->{},List.of());
        bubble.setSize(bubble.getPreferredSize());bubble.doLayout();
        JScrollPane math=findMath(bubble);require(math!=null,"tutor has native math scroller");
        math.doLayout();math.getViewport().doLayout();
        require(math.getViewport().getView() instanceof StudyHtmlPane,"vector renderer retained");
        int max=math.getHorizontalScrollBar().getMaximum()-math.getHorizontalScrollBar().getVisibleAmount();
        require(max>0,"long equation has a real scroll range");
        JEditorPane equation=(JEditorPane)math.getViewport().getView();
        require(equation.getUI().getRootView(equation).getMinimumSpan(javax.swing.text.View.X_AXIS)
            <=equation.getWidth(),"entire vector equation fits inside scrollable view");
        math.getHorizontalScrollBar().setValue(max/2);
        int before=math.getHorizontalScrollBar().getValue();
        Method update=type.getDeclaredMethod("updateContent",String.class,int.class,int.class);update.setAccessible(true);
        update.invoke(bubble,rendered+"<p>다음 스트리밍 문장</p>",width,font);
        bubble.doLayout();math.doLayout();math.getViewport().doLayout();
        require(findMath(bubble)==math,"streaming reuses same scroller");
        require(math.getHorizontalScrollBar().getValue()==before,"streaming preserves horizontal position");
        math.getHorizontalScrollBar().setValue(0);
        Method animate=type.getDeclaredMethod("animateSize",long.class);animate.setAccessible(true);
        long now=System.nanoTime();
        for(int i=1;i<=100;i++)animate.invoke(bubble,now+i*16_000_000L);
        bubble.setSize(bubble.getPreferredSize());bubble.doLayout();math.doLayout();math.getViewport().doLayout();
        BufferedImage image=new BufferedImage(width,bubble.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,width,image.getHeight());bubble.printAll(g);g.dispose();
        Path path=Path.of("build/tutor-bubble-check/scrollable-math.png");Files.createDirectories(path.getParent());ImageIO.write(image,"png",path.toFile());
        String again=StudyMarkdown.renderWithScrollableMath("적분값이에요.\n\n"+MATH+"\n\n마지막 설명이에요.",font,true,width-24);
        require(again.equals(rendered),"stable formula IDs across renders");
        String repeated=StudyMarkdown.renderWithScrollableMath(MATH+"\n\n다시 비교하면\n\n"+MATH,font,true,width-24);
        update.invoke(bubble,repeated,width,font);
        java.util.Set<Component> scrolls=java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        for(Component child:bubble.getComponents())if(child instanceof JScrollPane)scrolls.add(child);
        require(scrolls.size()==2,"repeated formulas have separate scroll views");
    }
    private static JScrollPane findMath(Container parent) {
        for(Component child:parent.getComponents())if(child instanceof JScrollPane scroll)return scroll;
        return null;
    }
    private static void require(boolean ok,String message) {if(!ok)throw new AssertionError(message);}
}
