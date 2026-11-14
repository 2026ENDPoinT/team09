package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.awt.datatransfer.Transferable;
import java.awt.image.BufferedImage;
import java.util.function.Supplier;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;

/** Exercises real card listeners without starting native DnD or opening a document. */
public final class PdfLibraryGestureTest {
    public static void main(String[] args)throws Exception {
        try {SwingUtilities.invokeAndWait(()->{try (PdfLibraryPanel library=new PdfLibraryPanel(Files.createTempDirectory("library-gesture-"),path->{})) {artwork();run(library,false);run(library,true);}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable error){error.printStackTrace();System.exit(1);}
        System.out.println("PdfLibraryGestureTest passed: jitter clicks once; thresholded drag exports once; drag remains a drag; folder/file children and buttons behave correctly.");System.exit(0);
    }
    private static void run(PdfLibraryPanel library,boolean folder)throws Exception {
        AtomicInteger opened=new AtomicInteger();JPanel card=new JPanel(null);card.setSize(280,250);
        JLabel child=new JLabel("파일 또는 폴더");child.setBounds(0,0,240,150);card.add(child);
        JButton button=new JButton("열기");button.setBounds(0,180,80,30);card.add(button);
        Method clickable=PdfLibraryPanel.class.getDeclaredMethod("clickable",Component.class,Runnable.class);clickable.setAccessible(true);
        clickable.invoke(null,card,(Runnable)opened::incrementAndGet);
        Class<?> payloadType=Class.forName(PdfLibraryPanel.class.getName()+"$LibraryDrag");
        Constructor<?> payload=payloadType.getDeclaredConstructor(String.class,boolean.class);payload.setAccessible(true);
        BufferedImage pixels=new BufferedImage(32,24,BufferedImage.TYPE_INT_ARGB);
        pixels.setRGB(16,12,Color.RED.getRGB());
        JLabel artwork=new JLabel(new ImageIcon(pixels));artwork.setSize(32,24);
        AtomicInteger captures=new AtomicInteger();
        Supplier<BufferedImage> preview=()->{captures.incrementAndGet();return LibraryDragPreview.capture(artwork);};
        Method enable=PdfLibraryPanel.class.getDeclaredMethod("enableLibraryDrag",Component.class,payloadType,Supplier.class);enable.setAccessible(true);
        enable.invoke(library,card,payload.newInstance("fixture",folder),preview);
        TransferHandler nativeHandler=child.getTransferHandler();
        check(nativeHandler==card.getTransferHandler(),"card children did not share one handler");
        check(captures.get()==0&&nativeHandler.getDragImage()==null,"preview allocated before a drag started");
        Method create=nativeHandler.getClass().getDeclaredMethod("createTransferable",JComponent.class);create.setAccessible(true);
        Method done=nativeHandler.getClass().getDeclaredMethod("exportDone",JComponent.class,Transferable.class,int.class);done.setAccessible(true);
        Transferable transfer=(Transferable)create.invoke(nativeHandler,child);
        check(captures.get()==1&&nativeHandler.getDragImage()!=null,"drag did not capture exactly one preview");
        BufferedImage image=(BufferedImage)nativeHandler.getDragImage();
        check(image.getRGB(16,12)==Color.RED.getRGB()&&image.getRGB(0,0)==0,"preview changed artwork or lost transparency");
        check(nativeHandler.getDragImageOffset().equals(new Point(-16,-12)),"preview did not stay centered on pointer");
        var flavor=transfer.getTransferDataFlavors()[0];Object first=transfer.getTransferData(flavor);
        check(first==transfer.getTransferData(flavor)&&captures.get()==1,"drag movement rebuilt the payload or preview");
        done.invoke(nativeHandler,child,transfer,TransferHandler.NONE);
        check(nativeHandler.getDragImage()==null,"cancelled drag retained preview pixels");
        pixels.setRGB(16,12,Color.BLUE.getRGB());
        Transferable next=(Transferable)create.invoke(nativeHandler,child);
        check(captures.get()==2&&((BufferedImage)nativeHandler.getDragImage()).getRGB(16,12)==Color.BLUE.getRGB(),
            "next drag reused stale artwork");
        done.invoke(nativeHandler,child,next,TransferHandler.MOVE);
        check(nativeHandler.getDragImage()==null,"completed drag retained preview pixels");
        Field minimum=PdfLibraryPanel.class.getDeclaredField("LIBRARY_DRAG_THRESHOLD");minimum.setAccessible(true);int threshold=minimum.getInt(null);
        check(threshold>=8,"threshold is too small");
        CountingTransfer handler=new CountingTransfer();child.setTransferHandler(handler);CountingTransfer rootHandler=new CountingTransfer();card.setTransferHandler(rootHandler);
        // Native CLICKED after release must not open a second time; an omitted CLICKED still opens.
        press(child,20,20);drag(child,21,21);release(child,21,21);clicked(child,21,21);
        check(opened.get()==1&&handler.calls==0,"tiny jitter was not exactly one click");
        press(child,20,20);drag(child,20+threshold-1,20);release(child,20+threshold-1,20);
        check(opened.get()==2&&handler.calls==0,"below-threshold movement started DnD or lost click");
        press(child,20,20);drag(child,20+threshold,20);drag(child,20+threshold+20,20);release(child,20+threshold+20,20);clicked(child,20+threshold+20,20);
        check(opened.get()==2&&handler.calls==1,"drag did not export exactly once or also opened");
        // Returning to the press point must not turn a completed drag back into a click.
        press(child,20,20);drag(child,20+threshold+2,20);drag(child,20,20);release(child,20,20);clicked(child,20,20);
        check(opened.get()==2&&handler.calls==2,"drag-return gesture opened the card");
        // A new press always discards an old gesture, including one with no release.
        press(child,20,20);drag(child,20+threshold,20);press(child,20,20);release(child,20,20);clicked(child,20,20);
        check(opened.get()==3&&handler.calls==3,"new click reused the old drag");
        drag(child,80,80);release(child,80,80);
        check(opened.get()==3&&handler.calls==3,"orphan motion started a gesture");
        press(card,20,20);drag(card,20+threshold,20);release(card,20+threshold,20);
        check(rootHandler.calls==1&&opened.get()==3,"card background differs from child");
        int before=opened.get();
        mouse(child,MouseEvent.MOUSE_PRESSED,20,20,InputEvent.CTRL_DOWN_MASK|InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1,true);
        mouse(child,MouseEvent.MOUSE_RELEASED,20,20,InputEvent.CTRL_DOWN_MASK,MouseEvent.BUTTON1,true);clicked(child,20,20);
        mouse(child,MouseEvent.MOUSE_PRESSED,20,20,InputEvent.BUTTON3_DOWN_MASK,MouseEvent.BUTTON3,true);
        mouse(child,MouseEvent.MOUSE_RELEASED,20,20,0,MouseEvent.BUTTON3,true);
        check(opened.get()==before&&handler.calls==3,"context menu gesture opened or dragged");
        check(button.getTransferHandler()==null,"embedded button became draggable");
        JPanel selectionOnly=new JPanel();selectionOnly.setSize(200,200);clickable.invoke(null,selectionOnly,(Runnable)opened::incrementAndGet);
        press(selectionOnly,20,20);drag(selectionOnly,21,21);release(selectionOnly,21,21);clicked(selectionOnly,21,21);
        check(opened.get()==before+1&&selectionOnly.getTransferHandler()==null,"selection-only click changed");
    }
    private static void artwork() {
        Icon folder=LibraryShelfDesign.folder(new Color(0x00ccb2),null);
        BufferedImage folderImage=LibraryDragPreview.icon(folder,new JLabel());
        check(folderImage.getWidth()<=160&&folderImage.getHeight()<=160,"folder preview exceeded pixel budget");
        check((folderImage.getRGB(0,0)>>>24)==0,"folder was replaced with an opaque card");
        check((folderImage.getRGB(folderImage.getWidth()/2,folderImage.getHeight()/2)>>>24)>0,"folder artwork missing");
        LibraryShelfDesign.PaperCover paper=new LibraryShelfDesign.PaperCover();paper.setSize(198,186);
        BufferedImage page=new BufferedImage(100,180,BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics=page.createGraphics();graphics.setColor(Color.MAGENTA);graphics.fillRect(0,0,100,180);graphics.dispose();
        paper.setIcon(new ImageIcon(page));
        BufferedImage document=LibraryDragPreview.capture(paper);
        check(document.getWidth()<=160&&document.getHeight()<=160,"document preview exceeded pixel budget");
        check((document.getRGB(0,0)>>>24)==0,"document margins lost transparency");
        check(document.getRGB(document.getWidth()/2,document.getHeight()/2)==Color.MAGENTA.getRGB(),"PDF cover was not captured");
    }
    private static final class CountingTransfer extends TransferHandler {
        int calls;
        @Override public void exportAsDrag(JComponent component,InputEvent event,int action){check(action==MOVE,"wrong action");calls++;}
    }
    private static void press(Component c,int x,int y){mouse(c,MouseEvent.MOUSE_PRESSED,x,y,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.BUTTON1,false);}
    private static void drag(Component c,int x,int y){mouse(c,MouseEvent.MOUSE_DRAGGED,x,y,InputEvent.BUTTON1_DOWN_MASK,MouseEvent.NOBUTTON,false);}
    private static void release(Component c,int x,int y){mouse(c,MouseEvent.MOUSE_RELEASED,x,y,0,MouseEvent.BUTTON1,false);}
    private static void clicked(Component c,int x,int y){mouse(c,MouseEvent.MOUSE_CLICKED,x,y,0,MouseEvent.BUTTON1,false);}
    private static void mouse(Component c,int id,int x,int y,int modifiers,int button,boolean popup){c.dispatchEvent(new MouseEvent(c,id,System.currentTimeMillis(),modifiers,x,y,0,0,1,popup,button));}
    private static void check(boolean condition,String reason){if(!condition)throw new AssertionError(reason);}
}
