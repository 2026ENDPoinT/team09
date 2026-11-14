package dev.synesis.poc.pdf;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.lang.reflect.*;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Real local import and shelf state; no provider calls or visible app. */
public final class PdfDropHomeTest {
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-drop-home-");
        for(int count:new int[]{1,2}) {
            Path root=base.resolve("library-"+count);List<Path> files=new ArrayList<>();
            for(int n=0;n<count;n++) {
                Path pdf=base.resolve("lesson-"+count+"-"+n+".pdf");
                try(PDDocument doc=new PDDocument()){for(int page=0;page<=n;page++)doc.addPage(new PDPage());doc.save(pdf.toFile());}
                files.add(pdf);
            }
            String oldId;try(PdfSource source=PdfSource.open(files.get(0),root)){oldId=source.id;}
            var org=PdfLibraryOrganization.load(root);var folder=org.createFolder("","수업");org.moveDocument(oldId,folder.id());
            for(Path file:files)try(PdfSource source=PdfSource.open(file,root)){PdfLibraryOrganization.load(root).moveDocument(source.id,folder.id());}
            Path retained=root.resolve(oldId).resolve("generated/keep.json");Files.createDirectories(retained.getParent());Files.writeString(retained,"preserve");
            CountDownLatch prepared=new CountDownLatch(count),release=new CountDownLatch(1);
            try(PdfBatchQueue queue=new PdfBatchQueue(root,p->null,s->{},()->{},true,(process,script,arguments,events)->{
                prepared.countDown();release.await(10,TimeUnit.SECONDS);throw new java.io.IOException("fixture stops before AI");
            })) {
                queue.submitAtHome(files);
                if(queue.snapshots().size()!=count)throw new AssertionError("Immediate import entries missing");
                if(!prepared.await(10,TimeUnit.SECONDS))throw new AssertionError("Local copies not prepared: "+queue.snapshots());
                var stored=PdfLibraryOrganization.load(root);
                for(var snapshot:queue.snapshots())if(!stored.location(snapshot.documentId()).isEmpty())throw new AssertionError("Dropped PDF stayed in subfolder");
                if(!Files.readString(retained).equals("preserve"))throw new AssertionError("Existing generated result changed");
                release.countDown();
            }
        }
        SwingUtilities.invokeAndWait(()->{
            PdfLibraryPanel panel=new PdfLibraryPanel(base.resolve("shelf"),p->{throw new AssertionError("Import must not open PDF");});
            try {
                panel.showImportHome();
                var pending=new PdfBatchQueue.Snapshot(1,null,"new.pdf",null,PdfBatchQueue.State.PREPARING,0,"copy",0);
                panel.setImportSnapshots(List.of(pending));
                Method method=PdfLibraryPanel.class.getDeclaredMethod("pendingImportCards");method.setAccessible(true);
                if(((List<?>)method.invoke(panel)).size()!=1)throw new AssertionError("Immediate placeholder missing");
                Field items=PdfLibraryPanel.class.getDeclaredField("items");items.setAccessible(true);
                String id="a".repeat(64);
                items.set(panel,List.of(new PdfLibraryStore.Item(id,base.resolve("source.pdf"),"new.pdf",java.time.Instant.now(),java.time.Instant.now())));
                panel.setImportSnapshots(List.of(new PdfBatchQueue.Snapshot(1,id,"new.pdf",base.resolve("source.pdf"),PdfBatchQueue.State.PREPARING,0,"prepare",0)));
                if(!((List<?>)method.invoke(panel)).isEmpty())throw new AssertionError("Real card and placeholder duplicated");
                panel.setImportSnapshots(List.of(new PdfBatchQueue.Snapshot(2,null,"bad.pdf",null,PdfBatchQueue.State.FAILED,0,"failed",0)));
                if(!((List<?>)method.invoke(panel)).isEmpty())throw new AssertionError("Failed import left ghost icon");
            }catch(ReflectiveOperationException e){throw new RuntimeException(e);}finally{panel.close();}
        });
        System.out.println("Single/bulk home imports, preserved data and immediate placeholder replacement passed");
    }
}
