package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.util.Map;
import java.nio.file.*;
import java.util.List;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Disposable library + no native windows/network; run only when Java build is authorized. */
public final class AssistantLibraryUiTest {
    private static void check(boolean value,String label){if(!value)throw new AssertionError(label);}
    public static void main(String[] args)throws Exception{
        Path base=Files.createTempDirectory("assistant-library-ui-");Path root=base.resolve("library");
        PdfLibraryOrganization org=PdfLibraryOrganization.load(root);
        var parent=org.createFolder("","폴더1");var child=org.createFolder(parent.id(),"폴더3");
        Path source=base.resolve("자료.pdf");try(PDDocument pdf=new PDDocument()){pdf.addPage(new PDPage());pdf.save(source.toFile());}
        String documentId;try(PdfSource pdf=PdfSource.open(source,root)){documentId=pdf.id;}
        // Re-load because import and the app store share the same virtual organization file.
        org=PdfLibraryOrganization.load(root);org.moveDocument(documentId,child.id());
        AtomicReference<Path> opened=new AtomicReference<>();AtomicLong openedAt=new AtomicLong();PdfLibraryPanel[] panel={null};
        SwingUtilities.invokeAndWait(()->{
            // A lightweight displayable hierarchy gives real child isShowing()/bounds
            // without creating a native window or bypassing source/target visibility.
            panel[0]=new PdfLibraryPanel(root,path->{opened.set(path);openedAt.set(System.nanoTime());},id->CompletableFuture.completedFuture(null),route->{});
            panel[0].addNotify();panel[0].setSize(1450,1050);layout(panel[0]);layout(panel[0]);
        });
        try{
            AssistantLibraryUi ui=panel[0].assistantLibraryUi();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
            while(true){
                try{ui.viewContext();break;}catch(Exception notReady){if(System.nanoTime()>deadline)throw notReady;Thread.sleep(10);}
            }
            JsonObject initial=ui.viewContext();check(initial.get("currentFolderId").getAsString().isEmpty(),"starts at virtual home");
            ui.navigateFolder(child.id()).toCompletableFuture().get(5,TimeUnit.SECONDS);
            check(ui.viewContext().get("currentPath").getAsString().equals("홈화면 > 폴더1 > 폴더3"),"full breadcrumb snapshot");
            check(ui.navigateFolder(child.id()).toCompletableFuture().get(5,TimeUnit.SECONDS).get("status").getAsString().equals("already_open"),"same folder no duplicate transition");
            ui.navigateFolder(parent.id()).toCompletableFuture().get(5,TimeUnit.SECONDS);
            check(ui.viewContext().get("currentFolderId").getAsString().equals(parent.id()),"ancestor navigation");
            check(!initial.get("viewRevision").equals(ui.viewContext().get("viewRevision")),"view revision follows navigation");
            long started=System.nanoTime();
            ui.openDocument(documentId).toCompletableFuture().get(5,TimeUnit.SECONDS);
            check(opened.get()!=null&&opened.get().getParent().getFileName().toString().equals(documentId),"exact normal file-open callback");
            check(openedAt.get()-started>=TimeUnit.MILLISECONDS.toNanos(190),"folder switch waits at least 200ms before click animation");
            check(ui.viewContext().get("currentFolderId").getAsString().equals(child.id()),"file's real parent opened first");
            navigationDuringOpen(ui,opened,documentId,parent.id(),child.id());
            navigationDuringSectionMotion(panel[0],ui,child.id());
            try{ui.openDocument("missing").toCompletableFuture().get(5,TimeUnit.SECONDS);throw new AssertionError("unknown file reported success");}catch(ExecutionException expected){}
            try{ui.navigateFolder("missing").toCompletableFuture().get(5,TimeUnit.SECONDS);throw new AssertionError("unknown folder reported success");}catch(ExecutionException expected){}
            rootMove(panel[0],ui,root,documentId);
            renameDisplay(panel[0],ui,root,documentId,parent.id());
            System.out.println("AssistantLibraryUiTest OK: folder context, navigation-independent opening, pending sidebar handoff, native flight and immediate renamed cards/breadcrumbs");
        }finally{SwingUtilities.invokeAndWait(()->{panel[0].close();panel[0].removeNotify();});}
    }
    private static void layout(Container container){container.doLayout();for(Component child:container.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    private static Object field(Object owner,String name)throws Exception{Field field=owner.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(owner);}
    private static Object panelField(PdfLibraryPanel panel,String name)throws Exception{Field field=PdfLibraryPanel.class.getDeclaredField(name);field.setAccessible(true);return field.get(panel);}
    private static Object record(Object owner,String name)throws Exception{Method method=owner.getClass().getDeclaredMethod(name);method.setAccessible(true);return method.invoke(owner);}
    private static boolean hasLabel(Container parent,String text){
        for(Component child:parent.getComponents()){
            if(child instanceof JLabel label&&text.equals(label.getText()))return true;
            if(child instanceof Container nested&&hasLabel(nested,text))return true;
        }
        return false;
    }
    private static void navigationDuringOpen(AssistantLibraryUi ui,AtomicReference<Path> opened,String documentId,String otherFolder,String documentFolder)throws Exception{
        ui.navigateFolder(otherFolder).toCompletableFuture().get(5,TimeUnit.SECONDS);opened.set(null);
        CompletableFuture<JsonObject> opening=ui.openDocument(documentId).toCompletableFuture();
        // The folder is now prepared, but the normal presentation pause is pending.
        SwingUtilities.invokeAndWait(()->{});
        check(!opening.isDone(),"fixture navigates before deferred open callback");
        ui.navigateFolder(otherFolder).toCompletableFuture().get(5,TimeUnit.SECONDS);
        JsonObject completed=opening.get(5,TimeUnit.SECONDS);
        check(completed.get("id").getAsString().equals(documentId)&&opened.get()!=null&&opened.get().getParent().getFileName().toString().equals(documentId),"screen movement preserves the original requested document");
        check(ui.viewContext().get("currentFolderId").getAsString().equals(otherFolder),"opening does not replace browsing with an unrelated document target");
        ui.navigateFolder(documentFolder).toCompletableFuture().get(5,TimeUnit.SECONDS);
    }
    private static void navigationDuringSectionMotion(PdfLibraryPanel panel,AssistantLibraryUi ui,String folderId)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{
            Method showPlanner=PdfLibraryPanel.class.getDeclaredMethod("showPlannerSection");showPlanner.setAccessible(true);showPlanner.invoke(panel);
        }catch(Exception failure){throw new RuntimeException(failure);}});
        ui.navigateFolder(folderId).toCompletableFuture().get(5,TimeUnit.SECONDS);
        Thread.sleep(250);SwingUtilities.invokeAndWait(()->{});
        JsonObject completed=ui.viewContext();
        check(completed.get("currentFolderId").getAsString().equals(folderId)&&completed.get("libraryVisible").getAsBoolean(),"explicit destination completes even during a replaceable sidebar transition");
    }
    private static void renameDisplay(PdfLibraryPanel panel,AssistantLibraryUi ui,Path root,String documentId,String folderId)throws Exception{
        String originalName=PdfLibraryStore.list(root).stream().filter(item->item.id().equals(documentId)).findFirst().orElseThrow().name();
        JsonArray changes=new JsonArray();
        for(String[] target:new String[][]{{"document",documentId,"수학 01.pdf"},{"folder",folderId,"정리한 폴더"}}){
            JsonObject change=new JsonObject();change.addProperty("operation","rename");change.addProperty("kind",target[0]);change.addProperty("id",target[1]);change.addProperty("name",target[2]);changes.add(change);
        }
        Object prepared=ui.prepareMutation(changes);AssistantLibrary store=new AssistantLibrary(root);
        JsonObject committed=store.apply("d".repeat(64),store.snapshot().get("revision").getAsString(),changes);
        ui.finishMutation(prepared,committed).toCompletableFuture().get(5,TimeUnit.SECONDS);
        check(ui.viewContext().get("currentPath").getAsString().equals("홈화면 > 정리한 폴더 > 폴더3"),"renamed ancestor immediately updates breadcrumb");
        ui.navigateFolder("").toCompletableFuture().get(5,TimeUnit.SECONDS);
        SwingUtilities.invokeAndWait(()->{try{
            JPanel card=(JPanel)((Map<?,?>)panelField(panel,"documentCards")).get(documentId);
            check(card!=null&&hasLabel(card,"수학 01.pdf"),"renamed document card uses committed name without manual refresh");
            JPanel folder=(JPanel)((Map<?,?>)panelField(panel,"folderCards")).get(folderId);
            check(folder!=null&&hasLabel(folder,"정리한 폴더"),"renamed folder card uses committed name");
        }catch(Exception error){throw new RuntimeException(error);}});
        Object undoTicket=ui.prepareMutation(new JsonArray());JsonObject undone=store.undo("e".repeat(64),"d".repeat(64));ui.finishMutation(undoTicket,undone).toCompletableFuture().get(5,TimeUnit.SECONDS);
        SwingUtilities.invokeAndWait(()->{try{
            JPanel card=(JPanel)((Map<?,?>)panelField(panel,"documentCards")).get(documentId);check(card!=null&&hasLabel(card,originalName),"undo immediately restores original document card name even without an old override");
            JPanel folder=(JPanel)((Map<?,?>)panelField(panel,"folderCards")).get(folderId);check(folder!=null&&hasLabel(folder,"폴더1"),"undo restores folder display");
        }catch(Exception error){throw new RuntimeException(error);}});
    }
    private static void rootMove(PdfLibraryPanel panel,AssistantLibraryUi ui,Path root,String id)throws Exception{
        JButton[] home={null};
        SwingUtilities.invokeAndWait(()->{try{
            layout(panel);layout(panel);
            JComponent paper=(JComponent)((Map<?,?>)panelField(panel,"covers")).get(id);
            check(paper!=null&&paper.isShowing()&&paper.getWidth()>0&&paper.getHeight()>0,"real source cover is displayable");
            home[0]=(JButton)((Map<?,?>)panelField(panel,"breadcrumbTargets")).get("");
            check(home[0]!=null&&home[0].isShowing()&&home[0].getWidth()>0&&home[0].getHeight()>0,"home breadcrumb has real hit/paint geometry");
        }catch(Exception error){throw new RuntimeException(error);}});
        JsonArray changes=new JsonArray();JsonObject move=new JsonObject();move.addProperty("operation","move");move.addProperty("kind","document");move.addProperty("id",id);move.addProperty("parentId","");changes.add(move);
        Object prepared=ui.prepareMutation(changes);
        List<?> visuals=(List<?>)record(prepared,"visuals");check(visuals.size()==1,"moving document captures one visible source, never silently zero");
        BufferedImage image=(BufferedImage)record(visuals.get(0),"image");boolean pixels=false;
        for(int y=0;y<image.getHeight()&&!pixels;y++)for(int x=0;x<image.getWidth();x++)if((image.getRGB(x,y)>>>24)!=0){pixels=true;break;}
        check(pixels,"captured flight sprite contains artwork pixels");
        AssistantLibrary store=new AssistantLibrary(root);JsonObject committed=store.apply("c".repeat(64),store.snapshot().get("revision").getAsString(),changes);
        CompletableFuture<JsonObject> finished=ui.finishMutation(prepared,committed).toCompletableFuture();
        AtomicBoolean inFlight=new AtomicBoolean();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(!inFlight.get()&&System.nanoTime()<deadline){
            SwingUtilities.invokeAndWait(()->{try{
                Object overlay=panelField(panel,"dropOverlay"),fly=field(overlay,"fly");
                if(fly==null)return;
                check(panelField(panel,"flyingTimer") instanceof javax.swing.Timer timer&&timer.isRunning(),"native fly timer is active");
                JButton current=(JButton)((Map<?,?>)panelField(panel,"breadcrumbTargets")).get("");
                check(current==home[0],"move-only flight retains pre-commit home breadcrumb rather than zero-bound replacement");
                JComponent layer=(JComponent)panelField(panel,"dropLayer");
                Point expected=SwingUtilities.convertPoint(current,current.getWidth()/2,current.getHeight()/2,layer);
                check(expected.equals(field(fly,"to")),"flight targets home breadcrumb center, including empty root ID");
                inFlight.set(true);
            }catch(Exception error){throw new RuntimeException(error);}});
            if(!inFlight.get())Thread.sleep(5);
        }
        check(inFlight.get(),"root move actually starts a native flight");
        JsonObject result=finished.get(5,TimeUnit.SECONDS);
        check(result.get("animationPreparedCount").getAsInt()==1&&result.get("animatedCount").getAsInt()==1,"capture and animated counts are explicit");
        check(result.get("animationCompleted").getAsBoolean()&&result.get("animationTargetId").getAsString().isEmpty(),"root destination flight completed");
        SwingUtilities.invokeAndWait(()->{try{check(panelField(panel,"flyingTimer")==null&&field(panelField(panel,"dropOverlay"),"fly")==null,"native timer and overlay clear after callback");}catch(Exception error){throw new RuntimeException(error);}});
        check(PdfLibraryOrganization.load(root).location(id).isEmpty(),"storage commits once to virtual root");
    }

}
