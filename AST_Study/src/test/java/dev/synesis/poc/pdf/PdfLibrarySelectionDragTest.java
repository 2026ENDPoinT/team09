package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryMotionClock;
import javax.swing.*;
import java.awt.*;
import java.awt.datatransfer.Transferable;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import org.apache.pdfbox.pdmodel.*;

/** No native windows: real selection handlers, hover navigation, atomic moves and bounded painting. */
public final class PdfLibrarySelectionDragTest {
    private static int checks;
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-multidrag-");PdfLibraryPanel[] panel={null};
        try {
            atomicMove(base.resolve("atomic"));
            Path root=base.resolve("library");PdfLibraryOrganization org=PdfLibraryOrganization.load(root);
            var folder=org.createFolder("","시험 범위");var child=org.createFolder(folder.id(),"하위 폴더");
            List<String> ids=new ArrayList<>();
            for(int i=0;i<4;i++) {
                Path file=base.resolve("문서"+i+".pdf");
                try(PDDocument pdf=new PDDocument()){for(int p=0;p<=i;p++)pdf.addPage(new PDPage());pdf.save(file.toFile());}
                try(PdfSource pdf=PdfSource.open(file,root)){ids.add(pdf.id);}
            }
            SwingUtilities.invokeAndWait(()->panel[0]=new PdfLibraryPanel(root,path->{throw new AssertionError("drag opened a PDF");},
                id->CompletableFuture.completedFuture(null),route->{}));
            long deadline=System.nanoTime()+10_000_000_000L;
            while(System.nanoTime()<deadline) {
                boolean[] ready={false};SwingUtilities.invokeAndWait(()->{try{ready[0]=((List<?>)get(panel[0],"items")).size()==4;}catch(Exception e){throw new RuntimeException(e);}});
                if(ready[0])break;Thread.sleep(20);
            }
            SwingUtilities.invokeAndWait(()->{try {
                PdfLibraryPanel library=panel[0];check(((List<?>)get(library,"items")).size()==4,"fixture did not load");
                set(library,"selectionMode",true);selected(library).addAll(ids.subList(0,3));show(library);
                library.setSize(1500,1050);layout(library);layout(library);
                Map<?,?> cards=(Map<?,?>)get(library,"documentCards");
                JComponent source=(JComponent)cards.get(ids.get(0));
                check(source.getTransferHandler()!=null,"selection mode disables dragging");
                TransferHandler handler=source.getTransferHandler();Transferable transfer=create(handler,source);
                Object payload=transfer.getTransferData(transfer.getTransferDataFlavors()[0]);
                List<?> dragged=(List<?>)access(payload,"documentIds");
                check(dragged.size()==3 && !dragged.contains(ids.get(3)),"selection includes an unselected file or loses a file");
                check(handler.getDragImage().getWidth(null)==1,"bulk transfer duplicates the overlay with a native preview");
                check((boolean)call(library,"canMove",payload,folder.id()),"valid folder rejected");
                check(!(boolean)call(library,"canMove",payload,""),"same-location move accepted");
                check(!(boolean)call(library,"canMove",payload,"missing-folder"),"unknown folder accepted");
                Object overlay=get(library,"dropOverlay");LibrarySelectionDrag motion=(LibrarySelectionDrag)get(overlay,"selection");
                check(motion!=null,"gather effect missing");
                LibraryMoveHint hint=(LibraryMoveHint)get(overlay,"hint");
                byte[] organizationBefore=Files.readAllBytes(root.resolve("library-organization.json"));
                check((boolean)call(library,"updateMoveHint",payload,folder.id(),new Point(600,400)),"valid folder has no move hint");
                check(hint.visible()&&hint.caption().contains(folder.name()),"hint does not name hovered folder");
                check(!(boolean)call(library,"updateMoveHint",payload,"",new Point(600,400))&&!hint.visible(),"no-op root drop shows move hint");
                check(!(boolean)call(library,"updateMoveHint",payload,"missing-folder",new Point(600,400))&&!hint.visible(),"missing folder shows move hint");
                check(Arrays.equals(organizationBefore,Files.readAllBytes(root.resolve("library-organization.json"))),"hover feedback writes library state");
                List<?> sprites=(List<?>)get(motion,"sprites");check(sprites.size()==3,"visible selected covers not captured individually");
                check(((BufferedImage)get(motion,"stack")).getWidth()==160,"cursor image grows with selection count");
                selected(library).remove(ids.get(1));check(dragged.size()==3,"payload follows mutable selection");selected(library).add(ids.get(1));
                try{((List<Object>)dragged).clear();throw new AssertionError("mutable drag payload");}catch(UnsupportedOperationException expected){checks++;}

                JComponent target=(JComponent)((Map<?,?>)get(library,"folderIcons")).get(folder.id());
                call(library,"armFolderHover",folder.id(),target);call(library,"beginFolderBlink");
                for(int i=0;i<4;i++)call(library,"advanceFolderBlink");
                check(folder.id().equals(get(library,"currentFolderId")),"hover did not open the folder");
                check(selected(library).containsAll(ids.subList(0,3)),"hover navigation cleared the drag selection");
                check(get(overlay,"selection")==motion,"hover navigation replaced the cursor effect");
                check((boolean)call(library,"canHoverFolder",payload,""),"cannot hover back to original location");
                Class<?> payloadType=payload.getClass();Constructor<?> ctor=payloadType.getDeclaredConstructor(String.class,boolean.class);ctor.setAccessible(true);
                Object folderDrag=ctor.newInstance(folder.id(),true);
                check(!(boolean)call(library,"canMove",folderDrag,child.id()),"folder can move into its child");
                check(!(boolean)call(library,"canHoverFolder",folderDrag,child.id()),"folder can hover into its own child");
                check(!(boolean)call(library,"updateMoveHint",folderDrag,child.id(),new Point(600,400))&&!hint.visible(),"descendant target shows a misleading folder move hint");
                Object childDrag=ctor.newInstance(child.id(),true);
                check((boolean)call(library,"updateMoveHint",childDrag,"",new Point(600,400))&&hint.caption().equals("홈 화면으로 이동"),"home breadcrumb does not identify a valid folder move");
                done(handler,source,transfer,TransferHandler.NONE);
                check(!hint.visible(),"cancel return keeps a move hint visible");
                check(get(overlay,"selection")==motion&&motion.isReturning(),"cancel must first return selected files to their origins");
                Method returnTick=LibraryMotionClock.class.getDeclaredMethod("tick",long.class);returnTick.setAccessible(true);
                returnTick.invoke(null,System.nanoTime()+LibrarySelectionDrag.DURATION+1);
                check(get(overlay,"selection")==null && get(library,"activeDocumentDrag")==null,"completed cancel return retains drag resources");
                check(handler.getDragImage()==null,"native image survives cancel");

                call(library,"enterFolder","");set(library,"listView",true);selected(library).addAll(ids.subList(0,3));show(library);layout(library);layout(library);
                JComponent row=(JComponent)((Map<?,?>)get(library,"documentCards")).get(ids.get(0));
                TransferHandler listHandler=row.getTransferHandler();Transferable listTransfer=create(listHandler,row);
                Object listPayload=listTransfer.getTransferData(listTransfer.getTransferDataFlavors()[0]);
                check(((List<?>)access(listPayload,"documentIds")).size()==3,"list view lost bulk drag");
                PdfLibraryOrganization live=(PdfLibraryOrganization)get(library,"organization");
                live.moveDocuments((List<String>)access(listPayload,"documentIds"),child.id());
                PdfLibraryOrganization restored=PdfLibraryOrganization.load(root);
                for(String id:ids.subList(0,3)) {
                    check(restored.location(id).equals(child.id()),"one selected PDF was not moved");
                    check(Files.isRegularFile(root.resolve(id).resolve("source.pdf")),"move changes PDF paths");
                }
                check(restored.location(ids.get(3)).isEmpty(),"unselected file moved");
                check((boolean)call(library,"updateMoveHint",listPayload,"",new Point(600,400))&&hint.caption().equals("홈 화면으로 이동"),"home breadcrumb does not identify a valid PDF move");
                done(listHandler,row,listTransfer,TransferHandler.MOVE);
                check(!hint.visible(),"completed move keeps a move hint visible");
                selected(library).add(ids.get(3));show(library);row=(JComponent)((Map<?,?>)get(library,"documentCards")).get(ids.get(3));
                TransferHandler single=row.getTransferHandler();Transferable one=create(single,row);
                check(single.getDragImage().getWidth(null)>1 && get(overlay,"selection")==null,"single selection no longer uses normal drag");
                done(single,row,one,TransferHandler.NONE);
                set(library,"selectionMode",false);show(library);layout(library);layout(library);
                row=(JComponent)((Map<?,?>)get(library,"documentCards")).get(ids.get(3));
                TransferHandler ordinary=row.getTransferHandler();Transferable ordinaryTransfer=create(ordinary,row);
                Object ordinaryPayload=ordinaryTransfer.getTransferData(ordinaryTransfer.getTransferDataFlavors()[0]);
                check((boolean)call(library,"updateMoveHint",ordinaryPayload,folder.id(),new Point(600,400))&&hint.visible(),"ordinary drag does not show a valid destination");
                done(ordinary,row,ordinaryTransfer,TransferHandler.NONE);check(!hint.visible(),"ordinary drag cancel keeps a move hint visible");
                motionBounds();
            }catch(Exception e){throw new RuntimeException(e);}});
            System.out.println("PdfLibrarySelectionDragTest passed: "+checks+" checks; bulk grid/list transfer, hover and breadcrumb navigation, immutable selection, atomic moves, bounded gather and cleanup.");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        finally{if(panel[0]!=null)SwingUtilities.invokeAndWait(panel[0]::close);}
        System.exit(0);
    }

    private static void atomicMove(Path root)throws Exception {
        PdfLibraryOrganization org=PdfLibraryOrganization.load(root);var target=org.createFolder("","대상");
        String a="a".repeat(64),b="b".repeat(64),c="c".repeat(64);org.moveDocument(c,target.id());
        org.moveDocuments(List.of(a,b),target.id());org=PdfLibraryOrganization.load(root);
        check(org.location(a).equals(target.id()) && org.location(b).equals(target.id()),"batch was not persisted");
        byte[] before=Files.readAllBytes(root.resolve("library-organization.json"));
        try{org.moveDocuments(List.of(a,"bad"),"");throw new AssertionError("bad ID accepted");}catch(IOException expected){checks++;}
        check(Arrays.equals(before,Files.readAllBytes(root.resolve("library-organization.json"))),"invalid group partially saved");
        Path file=root.resolve("library-organization.json");Files.delete(file);Files.createDirectory(file);Files.writeString(file.resolve("blocked"),"retain");
        try{org.moveDocuments(List.of(a,b),"");throw new AssertionError("failed save accepted");}catch(IOException expected){checks++;}
        check(org.location(a).equals(target.id())&&org.location(b).equals(target.id())&&org.location(c).equals(target.id()),"save failure did not restore all locations");
    }

    private static void motionBounds()throws Exception {
        JPanel surface=new JPanel(null);surface.setSize(1200,800);
        BufferedImage image=new BufferedImage(160,120,BufferedImage.TYPE_INT_ARGB_PRE);Graphics2D pixels=image.createGraphics();pixels.setColor(Color.RED);pixels.fillRect(0,0,160,120);pixels.dispose();
        List<LibrarySelectionDrag.Sprite> sprites=new ArrayList<>();
        for(int i=0;i<100;i++)sprites.add(new LibrarySelectionDrag.Sprite(image,new Point(100+(i%8)*110,100+(i/8)*50)));
        BufferedImage stack=LibraryDragPreview.stack(List.of(image),100);
        LibrarySelectionDrag motion=new LibrarySelectionDrag(surface,sprites,stack,new Point(600,400));
        check(((List<?>)get(motion,"sprites")).size()==12,"gather work grows without a bound");
        BufferedImage frame=new BufferedImage(1200,800,BufferedImage.TYPE_INT_ARGB_PRE);Graphics2D g=frame.createGraphics();
        try {
            motion.paint(g);check(frame.getRGB(100,100)!=0,"initial selected position is not painted");
            motion.move(new Point(650,450));check(get(motion,"stack")==stack,"pointer move reallocates its image");
            Method tick=LibraryMotionClock.class.getDeclaredMethod("tick",long.class);tick.setAccessible(true);
            tick.invoke(null,System.nanoTime()+LibrarySelectionDrag.DURATION+1);
            check(((List<?>)get(motion,"sprites")).isEmpty(),"gather retains individual captures");
            Method count=LibraryMotionClock.class.getDeclaredMethod("activeCount");count.setAccessible(true);
            check((int)count.invoke(null)==0,"completed gather keeps running a timer");
            motion.paint(g);check(frame.getRGB(650,450)!=0,"stack does not follow the pointer");
        } finally {g.dispose();motion.close();}
        check(get(motion,"stack")==null,"close retains stack pixels");
        UIManager.put("synesis.reduceMotion",true);
        try {motion=new LibrarySelectionDrag(surface,sprites,stack,new Point());check(((List<?>)get(motion,"sprites")).isEmpty(),"reduced motion still animates");motion.close();}
        finally {UIManager.put("synesis.reduceMotion",null);}
    }

    private static Transferable create(TransferHandler handler,JComponent source)throws Exception {Method m=handler.getClass().getDeclaredMethod("createTransferable",JComponent.class);m.setAccessible(true);return (Transferable)m.invoke(handler,source);}
    private static void done(TransferHandler handler,JComponent source,Transferable value,int action)throws Exception {Method m=handler.getClass().getDeclaredMethod("exportDone",JComponent.class,Transferable.class,int.class);m.setAccessible(true);m.invoke(handler,source,value,action);}
    private static Object access(Object o,String name)throws Exception {Method m=o.getClass().getDeclaredMethod(name);m.setAccessible(true);return m.invoke(o);}
    private static Object get(Object o,String name)throws Exception {Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object value)throws Exception {Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    private static Object call(Object o,String name,Object...args)throws Exception {for(Method m:o.getClass().getDeclaredMethods())if(m.getName().equals(name)&&m.getParameterCount()==args.length){m.setAccessible(true);return m.invoke(o,args);}throw new NoSuchMethodException(name);}
    private static Set<String> selected(PdfLibraryPanel library)throws Exception {return (Set<String>)get(library,"selectedIds");}
    private static void show(PdfLibraryPanel library)throws Exception {call(library,"showItems");}
    private static void layout(Container c){c.doLayout();for(Component x:c.getComponents())if(x instanceof Container child)layout(child);}
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
}
