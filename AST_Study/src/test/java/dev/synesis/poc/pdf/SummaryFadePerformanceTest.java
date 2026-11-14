package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;

/** A saved-summary fade paints rich prose once; scrolling/clicking immediately restores live content. */
public final class SummaryFadePerformanceTest {
    static class Counted extends JPanel {
        int paints;
        @Override protected void paintComponent(Graphics g){paints++;super.paintComponent(g);g.drawString("읽기와 선택이 가능한 본문",20,50);}
    }
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-summary-fade-");
        SwingUtilities.invokeAndWait(()->{try(PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("library"))) {
            JScrollPane scroll=(JScrollPane)get(workspace,"summaryScroll");
            @SuppressWarnings("unchecked") JLayer<JScrollPane> layer=(JLayer<JScrollPane>)get(workspace,"summaryFadeLayer");
            Counted view=new Counted();view.setBackground(Color.WHITE);view.setPreferredSize(new Dimension(500,1400));scroll.setViewportView(view);
            layer.setSize(540,360);layout(layer);set(workspace,"summaryFadeAlpha",.5f);
            BufferedImage canvas=new BufferedImage(540,360,BufferedImage.TYPE_INT_RGB);Graphics2D g=canvas.createGraphics();
            try {
                layer.printAll(g);int first=view.paints;Object snapshot=get(workspace,"summaryFadeSnapshot");
                check(first>0&&snapshot!=null,"first fade frame captures the actual viewport");
                for(int i=0;i<20;i++)layer.printAll(g);
                check(view.paints==first&&snapshot==get(workspace,"summaryFadeSnapshot"),"subsequent fade frames do not repaint rich text");
                MouseWheelEvent wheel=new MouseWheelEvent(view,MouseEvent.MOUSE_WHEEL,0,0,10,10,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,1);
                layer.getUI().eventDispatched(wheel,layer);
                check((float)get(workspace,"summaryFadeAlpha")==0&&get(workspace,"summaryFadeSnapshot")==null,"wheel interaction releases the frozen frame immediately");
                check(!wheel.isConsumed(),"fade interruption preserves native precise wheel input");
                layer.printAll(g);check(view.paints>first,"live selectable content resumes after interruption");
            } finally {g.dispose();}
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: single-paint saved-summary fade, frame reuse, prompt wheel handling and snapshot cleanup");System.exit(0);
    }
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
}
