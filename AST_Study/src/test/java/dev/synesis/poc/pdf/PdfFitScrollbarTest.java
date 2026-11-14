package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.ComponentEvent;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.common.PDRectangle;

/** No windows or PDF rendering: exercise native scroll layout at short-document fit thresholds. */
public final class PdfFitScrollbarTest {
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-pdf-fit-scroll-");
        Path pdf=root.resolve("three-landscape-pages.pdf");
        try(PDDocument doc=new PDDocument()) {
            for(int i=0;i<3;i++)doc.addPage(new PDPage(new PDRectangle(960,540)));
            doc.save(pdf.toFile());
        }
        try(PdfSource source=PdfSource.open(pdf,root.resolve("library"))) {
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("library"));
                try {check(workspace,source);}catch(Exception e){throw new RuntimeException(e);}
                finally {workspace.close();}
            });
        } catch(Throwable error) {error.printStackTrace();System.exit(1);}
        System.out.println("PdfFitScrollbarTest passed: short-document thresholds, both scrollbars and numeric zoom");
        System.exit(0);
    }

    private static void check(PdfWorkspace workspace,PdfSource source)throws Exception {
        field("source").set(workspace,source);
        JScrollPane scroll=(JScrollPane)field("imageScroll").get(workspace);
        JPanel canvas=(JPanel)field("imageCanvas").get(workspace);
        JComboBox<?> zoom=(JComboBox<?>)field("zoom").get(workspace);
        Method layout=PdfWorkspace.class.getDeclaredMethod("layoutPdfPages",PdfSource.class);
        layout.setAccessible(true);
        field("updatingPdfZoom").setBoolean(workspace,true);
        zoom.setSelectedItem("너비 맞춤");
        boolean withBar=false,withoutBar=false;
        for(int width=360;width<=900;width+=30) {
            int threshold=16+3*(Math.round((width-32)*540f/960)+16);
            for(int height=threshold-60;height<=threshold+20;height+=2) {
                scroll.setSize(width,height);
                String settled=null;
                for(int round=0;round<16;round++) {
                    scroll.doLayout();scroll.getViewport().doLayout();
                    layout.invoke(workspace,source);
                    scroll.doLayout();scroll.getViewport().doLayout();
                    Dimension extent=scroll.getViewport().getExtentSize();
                    Dimension content=canvas.getPreferredSize();
                    String state=extent+"/"+content+"/"+scroll.getVerticalScrollBar().isVisible()+"/"+scroll.getHorizontalScrollBar().isVisible();
                    if(round==8)settled=state;
                    if(round>8 && !state.equals(settled))throw new AssertionError(
                        "fit layout oscillates at "+width+"x"+height+": "+settled+" -> "+state);
                    if(round>8 && scroll.getHorizontalScrollBar().isVisible())throw new AssertionError(
                        "fit-width introduced horizontal overflow at "+width+"x"+height);
                }
                if(scroll.getVerticalScrollBar().isVisible())withBar=true;else withoutBar=true;
            }
        }
        if(!withBar || !withoutBar)throw new AssertionError("test must exercise both sides of overflow threshold");
        scroll.setSize(640,1200);
        scroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_NEVER);
        scroll.doLayout();layout.invoke(workspace,source);scroll.doLayout();scroll.getViewport().doLayout();
        Method width=PdfWorkspace.class.getDeclaredMethod("pdfLayoutWidth");width.setAccessible(true);
        int stableWidth=(int)width.invoke(workspace);
        field("lastViewportWidth").setInt(workspace,stableWidth);
        field("lastViewportHeight").setInt(workspace,scroll.getViewport().getHeight());
        AtomicInteger generation=(AtomicInteger)field("renderGeneration").get(workspace);
        int previousGeneration=generation.get();
        @SuppressWarnings("unchecked") Map<Integer,BufferedImage> cache=(Map<Integer,BufferedImage>)field("pageBitmaps").get(workspace);
        BufferedImage retained=new BufferedImage(1,1,BufferedImage.TYPE_INT_RGB);cache.put(1,retained);
        for(int policy:new int[]{JScrollPane.VERTICAL_SCROLLBAR_ALWAYS,JScrollPane.VERTICAL_SCROLLBAR_NEVER}) {
            scroll.setVerticalScrollBarPolicy(policy);scroll.doLayout();scroll.getViewport().doLayout();
            for(var listener:scroll.getViewport().getComponentListeners())
                listener.componentResized(new ComponentEvent(scroll.getViewport(),ComponentEvent.COMPONENT_RESIZED));
            if((int)width.invoke(workspace)!=stableWidth || generation.get()!=previousGeneration || cache.get(1)!=retained)
                throw new AssertionError("scrollbar-only resize changed fit width, rendered again or cleared PDF cache");
        }
        scroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED);
        zoom.setSelectedItem("150%");scroll.setSize(500,600);
        for(int i=0;i<4;i++){layout.invoke(workspace,source);scroll.doLayout();scroll.getViewport().doLayout();}
        if(!scroll.getHorizontalScrollBar().isVisible())throw new AssertionError("numeric zoom lost horizontal scrolling");
    }

    private static Field field(String name)throws Exception {
        Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field;
    }
}
