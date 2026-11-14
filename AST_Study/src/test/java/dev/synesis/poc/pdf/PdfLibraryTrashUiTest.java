package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicInteger;
import javax.imageio.ImageIO;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Real shelf handlers and menu state on disposable files; no windows or deletion dialogs. */
public final class PdfLibraryTrashUiTest {
    private static int checks;
    private static void check(boolean condition,String message){checks++;if(!condition)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        Path base=Files.createTempDirectory("synesis-trash-ui-"),root=base.resolve("library");
        List<String> ids=new ArrayList<>();
        for(int i=0;i<2;i++){
            Path path=base.resolve("문서"+i+".pdf");
            try(PDDocument doc=new PDDocument()){for(int p=0;p<=i;p++)doc.addPage(new PDPage());doc.save(path.toFile());}
            try(PdfSource source=PdfSource.open(path,root)){ids.add(source.id);}
        }
        var org=PdfLibraryOrganization.load(root);var folder=org.createFolder("","수업 자료");org.moveDocument(ids.get(0),folder.id());
        AtomicInteger releases=new AtomicInteger();PdfLibraryPanel[] panel={null};
        try{
            edt(()->panel[0]=new PdfLibraryPanel(root,p->{throw new AssertionError("trash opened document");},id->{releases.incrementAndGet();return CompletableFuture.completedFuture(null);},s->{}));
            await(()->{try{return ((List<?>)get(panel[0],"items")).size()==2&&((PdfLibraryOrganization)get(panel[0],"organization")).folder(PdfLibraryOrganization.TRASH_ID)!=null;}catch(Exception e){return false;}});
            PdfLibraryPanel library=panel[0];
            edt(()->{
                @SuppressWarnings("unchecked") List<PdfLibraryStore.Item> items=(List<PdfLibraryStore.Item>)get(library,"items");
                PdfLibraryStore.Item home=items.stream().filter(item->item.id().equals(ids.get(1))).findFirst().orElseThrow();
                JPopupMenu menu=(JPopupMenu)call(library,"documentActions",home,new JButton());
                check(texts(menu).contains("휴지통으로 이동시키기")&&!texts(menu).contains("파일 삭제"),"home document menu still deletes files");
                check(texts(menu).contains("데이터 삭제"),"data delete option missing");
                check(!texts(menu).contains("복원하기")&&!((JButton)get(library,"restoreSelected")).isVisible(),"restore exposed outside trash");
                set(library,"selectionMode",true);call(library,"showItems");
                Map<?,?> cards=(Map<?,?>)get(library,"folderCards");
                check(hasCheckbox((Container)cards.get(folder.id())),"grid folders cannot be selected");
                check(!hasCheckbox((Container)cards.get(PdfLibraryOrganization.TRASH_ID)),"system trash can be selected for deletion");
                set(library,"listView",true);call(library,"showItems");cards=(Map<?,?>)get(library,"folderCards");
                check(hasCheckbox((Container)cards.get(folder.id())),"list folders cannot be selected");
                ((JButton)get(library,"selectAll")).doClick();
                check(((Set<?>)get(library,"selectedIds")).size()==1&&((Set<?>)get(library,"selectedFolderIds")).equals(Set.of(folder.id())),"bulk selection lost folders or includes trash itself");
                check(((JButton)get(library,"deleteSelectedFiles")).getText().equals("휴지통으로 이동시키기"),"home bulk label incorrect");
                call(library,"deleteSelected",true);
            });
            await(()->{try{var next=PdfLibraryOrganization.load(root);return next.isDocumentInTrash(ids.get(0))&&next.isDocumentInTrash(ids.get(1));}catch(Exception e){return false;}});
            await(()->{try{return ((PdfLibraryOrganization)get(library,"organization")).isDocumentInTrash(ids.get(1))&&((Map<?,?>)get(library,"documentCards")).isEmpty();}catch(Exception e){return false;}});
            edt(()->{
                check(releases.get()==0,"trash move closed a running document/task");
                for(String id:ids)check(Files.isRegularFile(root.resolve(id).resolve("source.pdf")),"trash move deleted a PDF");
                call(library,"enterFolder",PdfLibraryOrganization.TRASH_ID);
                check(((JButton)get(library,"deleteSelectedFiles")).getText().equals("영구 삭제하기"),"trash bulk label incorrect");
                @SuppressWarnings("unchecked") List<PdfLibraryStore.Item> items=(List<PdfLibraryStore.Item>)get(library,"items");
                var item=items.stream().filter(x->x.id().equals(ids.get(1))).findFirst().orElseThrow();
                JPopupMenu document=(JPopupMenu)call(library,"documentActions",item,new JButton());
                check(texts(document).contains("복원하기"),"trash document restore menu missing");
                check(((JButton)get(library,"restoreSelected")).isVisible(),"bulk restore missing in trash");
                check(texts(document).contains("영구 삭제하기")&&!texts(document).contains("휴지통으로 이동시키기"),"trash document menu incorrect");
                var current=(PdfLibraryOrganization)get(library,"organization");
                JPopupMenu folders=(JPopupMenu)call(library,"folderActions",current.folder(folder.id()),new JPanel(),new JButton());
                check(texts(folders).contains("복원하기"),"trash folder restore menu missing");
                check(texts(folders).contains("영구 삭제하기"),"trash folder menu does not permanently delete");
                JPopupMenu trash=(JPopupMenu)call(library,"folderActions",current.folder(PdfLibraryOrganization.TRASH_ID),new JPanel(),new JButton());
                check(!texts(trash).contains("영구 삭제하기")&&!texts(trash).contains("이름 변경"),"system trash can be removed/renamed");
                call(library,"enterFolder","");set(library,"recentSection",true);call(library,"showItems");
                check(((Map<?,?>)get(library,"documentCards")).isEmpty(),"recent shelf resurrects discarded files");
                renderAndCheckArtwork();
            });
            // Invoke the real right-click restore handler; no native window/dialog.
            edt(()->{
                set(library,"recentSection",false);call(library,"enterFolder",PdfLibraryOrganization.TRASH_ID);
                @SuppressWarnings("unchecked") List<PdfLibraryStore.Item> items=(List<PdfLibraryStore.Item>)get(library,"items");
                var item=items.stream().filter(x->x.id().equals(ids.get(1))).findFirst().orElseThrow();
                JPopupMenu menu=(JPopupMenu)call(library,"documentActions",item,new JButton());
                for(Component component:menu.getComponents())if(component instanceof JMenuItem action&&action.getText().equals("복원하기"))action.doClick();
            });
            await(()->{try{return !PdfLibraryOrganization.load(root).isDocumentInTrash(ids.get(1))&&((Map<?,?>)get(library,"documentCards")).isEmpty();}catch(Exception error){return false;}});
            edt(()->{
                check(releases.get()==0,"single restore closed an open task");set(library,"selectionMode",true);call(library,"showItems");
                ((JButton)get(library,"selectAll")).doClick();check(((JButton)get(library,"restoreSelected")).isEnabled(),"selected bulk restore disabled");
                ((JButton)get(library,"restoreSelected")).doClick();
            });
            await(()->{try{return !PdfLibraryOrganization.load(root).isDocumentInTrash(ids.get(0))&&((Set<?>)get(library,"selectedFolderIds")).isEmpty();}catch(Exception error){return false;}});
            check(PdfLibraryOrganization.load(root).location(ids.get(0)).equals(folder.id()),"bulk restore lost original subfolder");
            check(releases.get()==0,"bulk restore closed an open task");
            System.out.println("PdfLibraryTrashUiTest passed: "+checks+" menu, mixed grid/list selection, task-preservation and artwork checks");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        finally{if(panel[0]!=null)edt(panel[0]::close);}
        System.exit(0);
    }
    private static void renderAndCheckArtwork()throws Exception{
        Icon art=LibraryShelfDesign.trash(),small=LibraryShelfDesign.trash(16);
        check(art==LibraryShelfDesign.trash()&&small==LibraryShelfDesign.trash(16),"trash artwork/icon allocated on refresh");
        BufferedImage preview=new BufferedImage(594,474,BufferedImage.TYPE_INT_ARGB);Graphics2D g=preview.createGraphics();
        try{g.scale(3,3);art.paintIcon(null,g,0,0);}finally{g.dispose();}
        Field raster=art.getClass().getDeclaredField("raster");raster.setAccessible(true);Object retained=raster.get(art);
        BufferedImage canvas=new BufferedImage(40,40,BufferedImage.TYPE_INT_ARGB);g=canvas.createGraphics();
        try{for(int i=0;i<10;i++)small.paintIcon(null,g,0,0);}finally{g.dispose();}
        check(raster.get(art)==retained,"small icon thrashes large artwork cache");
        Path out=Path.of("build/validation/library-trash/icon-preview.png");Files.createDirectories(out.getParent());ImageIO.write(preview,"png",out.toFile());
    }
    private interface Task{void run()throws Exception;}
    private interface Ready{boolean get();}
    private static void edt(Task task)throws Exception{SwingUtilities.invokeAndWait(()->{try{task.run();}catch(Exception e){throw new RuntimeException(e);}});}
    private static void await(Ready condition)throws Exception{long end=System.nanoTime()+8_000_000_000L;while(System.nanoTime()<end){boolean[] ready={false};edt(()->ready[0]=condition.get());if(ready[0])return;Thread.sleep(20);}throw new AssertionError("shelf did not settle");}
    private static List<String> texts(JPopupMenu menu){List<String> out=new ArrayList<>();for(Component c:menu.getComponents())if(c instanceof JMenuItem item)out.add(item.getText());return out;}
    private static boolean hasCheckbox(Container container){for(Component c:container.getComponents())if(c instanceof JCheckBox||c instanceof Container child&&hasCheckbox(child))return true;return false;}
    private static Object get(Object target,String name)throws Exception{Field f=PdfLibraryPanel.class.getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void set(Object target,String name,Object value)throws Exception{Field f=PdfLibraryPanel.class.getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    private static Object call(Object target,String name,Object...args)throws Exception{for(Method method:PdfLibraryPanel.class.getDeclaredMethods())if(method.getName().equals(name)&&method.getParameterCount()==args.length){method.setAccessible(true);return method.invoke(target,args);}throw new NoSuchMethodException(name);}
}
