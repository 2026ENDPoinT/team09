package dev.synesis.poc.pdf;

import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.common.PDRectangle;

/** Real nested splits and queued resize/render events, without a window or remote work. */
public final class PdfOuterPanelPageTest {
    private static PdfWorkspace w;
    private static JSplitPane outer;
    private static JPanel mentor;
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("pdf-outer-page-");Path file=root.resolve("source.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<17;i++)doc.addPage(new PDPage(new PDRectangle(800,450)));doc.save(file.toFile());}
        try(PdfSource source=PdfSource.open(file,root.resolve("library"))) {
            try {
                edt(()->{
                    w=new PdfWorkspace(false,root.resolve("library"));set(w,"source",source);
                    ((JSpinner)get(w,"pageNumber")).setModel(new SpinnerNumberModel(1,1,17,1));
                    mentor=new JPanel();mentor.setMinimumSize(new Dimension(0,0));
                    outer=new JSplitPane(JSplitPane.HORIZONTAL_SPLIT,w,null);outer.setSize(1400,780);outer.setDividerSize(0);
                    layout(outer);call(w,"renderPage",new Class<?>[]{});
                });
                drain();
                for(int round=0;round<3;round++)for(boolean opening:new boolean[]{true,false}) {
                    edt(()->w.showPage(14));drain();
                    edt(()->{
                        w.preparePanelLayoutChange();
                        if(opening){outer.setRightComponent(mentor);outer.setDividerSize(4);}
                        w.setSidePanelVisible(opening,false);
                        // Commit an intermediate width, as the outer transition does.
                        outer.setDividerLocation(opening?1150:1200);layout(outer);
                    });
                    Thread.sleep(230); // longer than both old resize debounce timers
                    edt(()->{
                        if(!((JSpinner)get(w,"pageNumber")).getValue().equals(14))throw new AssertionError("page changed mid-transition");
                        if(get(w,"panelLayoutAnchor")==null)throw new AssertionError("page released before outer completion");
                        if(opening)outer.setDividerLocation(980);
                        else{outer.setRightComponent(null);outer.setDividerSize(0);}
                        layout(outer);w.settleSidePanelLayout();layout(outer);
                        w.completePanelLayoutChange();
                    });
                    drain();Thread.sleep(400);drain();
                    edt(()->{
                        layout(outer);
                        if(!((JSpinner)get(w,"pageNumber")).getValue().equals(14))throw new AssertionError("displayed page lost after outer completion");
                        Object anchor=call(w,"captureZoomAnchor",new Class<?>[]{Point.class,Point.class},null,null);
                        Method page=anchor.getClass().getDeclaredMethod("page"),y=anchor.getClass().getDeclaredMethod("yFraction");page.setAccessible(true);y.setAccessible(true);
                        if(!page.invoke(anchor).equals(14)||Math.abs((double)y.invoke(anchor)-.5)>.015)
                            throw new AssertionError("page 14 is not centered after nested layout: "+anchor);
                        if(get(w,"panelLayoutAnchor")!=null)throw new AssertionError("page remains pinned after completion");
                    });
                }
            }finally{if(w!=null)edt(()->w.close());}
        }
        System.out.println("PdfOuterPanelPageTest OK");System.exit(0);
    }
    private interface Task {void run()throws Exception;}
    private static void edt(Task task)throws Exception {SwingUtilities.invokeAndWait(()->{try{task.run();}catch(Exception e){throw new RuntimeException(e);}});}
    private static void drain()throws Exception{for(int i=0;i<5;i++)edt(()->{});}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    private static Object get(Object o,String name)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object v)throws Exception{Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);f.set(o,v);}
    private static Object call(Object o,String name,Class<?>[] types,Object...args)throws Exception{Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(o,args);}
}
