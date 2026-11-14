package dev.synesis.poc.pdf;

import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Offline panel toggles preserve the visible page, using the NEW viewport center. */
public final class PdfPanelAnchorTest {
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("pdf-panel-anchor-");Path file=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<8;i++)doc.addPage(new PDPage());doc.save(file.toFile());}
        try(PdfSource source=PdfSource.open(file,root.resolve("library"))) {
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace w=new PdfWorkspace(false,root.resolve("library"));
                try {
                    Field f=PdfWorkspace.class.getDeclaredField("source");f.setAccessible(true);f.set(w,source);
                    ((JSpinner)get(w,"pageNumber")).setModel(new SpinnerNumberModel(1,1,8,1));
                    JScrollPane scroll=(JScrollPane)get(w,"imageScroll");scroll.getViewport().setExtentSize(new Dimension(500,450));
                    call(w,"layoutPdfPages",new Class<?>[]{PdfSource.class},source);
                    Class<?> anchor=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$ZoomAnchor");
                    Constructor<?> ctor=anchor.getDeclaredConstructors()[0];ctor.setAccessible(true);
                    Object initial=ctor.newInstance(4,.5,.5,-1,-1);
                    call(w,"restoreZoomAnchor",new Class<?>[]{anchor},initial);
                    // Simulate a still-visible old page while the displayed number
                    // already identifies the user's target. The number must win.
                    f.set(w,null);
                    ((JSpinner)get(w,"pageNumber")).setValue(6);
                    f.set(w,source);
                    for(String toggle:new String[]{"setLearningVisible","setLearningVisible","setSidePanelVisible","setSidePanelVisible"}) {
                        boolean show=toggle.equals("setLearningVisible")?(boolean)get(w,"learningVisible"):(boolean)get(w,"sidePanelVisible");
                        call(w,toggle,new Class<?>[]{boolean.class},!show);
                        Object saved=get(w,"pendingLayoutAnchor");
                        if(saved==null)throw new AssertionError("panel change lost anchor");
                        Method page=anchor.getDeclaredMethod("page");page.setAccessible(true);
                        if(!page.invoke(saved).equals(6))throw new AssertionError("displayed page number lost");
                        // The resize debounce may consume its one-shot anchor
                        // before later animation events. A temporary top-of-PDF
                        // viewport must not replace the pinned displayed number.
                        Field pending=PdfWorkspace.class.getDeclaredField("pendingLayoutAnchor");pending.setAccessible(true);pending.set(w,null);
                        scroll.getViewport().setViewPosition(new Point(0,0));
                        call(w,"updatePageFromScroll",new Class<?>[]{});
                        if(!((JSpinner)get(w,"pageNumber")).getValue().equals(6))
                            throw new AssertionError("intermediate resize replaced displayed page number");
                        scroll.getViewport().setExtentSize(new Dimension(show?900:400,450));
                        call(w,"layoutPdfPages",new Class<?>[]{PdfSource.class},source);
                        call(w,"restoreZoomAnchor",new Class<?>[]{anchor},saved);
                        Object centered=call(w,"captureZoomAnchor",new Class<?>[]{Point.class,Point.class},null,null);
                        Method fraction=anchor.getDeclaredMethod("yFraction");fraction.setAccessible(true);
                        if(!page.invoke(centered).equals(6)||Math.abs((double)fraction.invoke(centered)-.5)>.003)
                            throw new AssertionError("page is not centered after panel toggle");
                    }
                    w.showPage(2);
                    if(get(w,"panelLayoutAnchor")!=null)throw new AssertionError("explicit page navigation was pinned");
                }catch(Exception e){throw new RuntimeException(e);}finally{w.close();}
            });
        }
        System.out.println("PdfPanelAnchorTest OK");System.exit(0);
    }
    private static Object get(Object w,String name)throws Exception {Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(w);}
    private static Object call(Object w,String name,Class<?>[] types,Object...args)throws Exception {Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(w,args);}
}
