package dev.synesis.poc.pdf;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import org.apache.pdfbox.pdmodel.*;

/** Mixed import settings exercise real copies/placement; provider execution is a local fixture. */
public final class PdfImportChoicesTest {
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-import-settings-"),root=base.resolve("library");
        List<Path> files=new ArrayList<>();
        for(int i=0;i<3;i++) {
            Path file=base.resolve("lesson-"+i+".pdf");
            try(PDDocument doc=new PDDocument()){for(int p=0;p<=i;p++)doc.addPage(new PDPage());doc.save(file.toFile());}
            files.add(file);
        }
        var org=PdfLibraryOrganization.load(root);var first=org.createFolder("","수업");var second=org.createFolder(first.id(),"과제");
        Set<Path> calls=ConcurrentHashMap.newKeySet();
        try(var queue=new PdfBatchQueue(root,p->{throw new AssertionError("No extra approval for automatic mode");},s->{},()->{},true,
            (process,script,arguments,events)->{
                Path folder=Path.of(arguments.get(arguments.indexOf("--folder")+1));calls.add(folder);
                if(script.equals("pdf_pipeline.py"))Files.writeString(folder.resolve("document.json"),"{\"pages\":[{},{}]}");
                if(arguments.contains("--request")) {
                    Path request=Path.of(arguments.get(arguments.indexOf("--request")+1));
                    var payload=com.google.gson.JsonParser.parseString(Files.readString(request)).getAsJsonObject();
                    if(!payload.get("strategy").getAsString().equals("newest-k1"))throw new AssertionError("Selected engine lost: "+payload);
                    Path result=request.resolveSibling(request.getFileName().toString().replace(".json",".result.json"));
                    Files.writeString(result,arguments.get(0).equals("group-plan")?"{\"totalCostEstimateUsd\":0}":"{}");
                }
            })) {
            queue.submitImports(List.of(new PdfBatchQueue.ImportChoice(files.get(0),first.id(),false),
                new PdfBatchQueue.ImportChoice(files.get(1),second.id(),true,"newest-k1"),
                new PdfBatchQueue.ImportChoice(files.get(2),"",false)));
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
            while(queue.snapshots().stream().anyMatch(s->s.state()!=PdfBatchQueue.State.COMPLETE) && System.nanoTime()<deadline)Thread.sleep(20);
            var snapshots=queue.snapshots();
            if(snapshots.size()!=3 || snapshots.stream().anyMatch(s->s.state()!=PdfBatchQueue.State.COMPLETE))throw new AssertionError(snapshots);
            if(!snapshots.get(1).strategy().equals("newest-k1") || !snapshots.get(0).strategy().equals(PdfStudyStrategy.DEFAULT))throw new AssertionError("Snapshot engine identity lost");
            var stored=PdfLibraryOrganization.load(root);
            List<String> destinations=List.of(first.id(),second.id(),"");
            for(int i=0;i<3;i++) {
                var snapshot=snapshots.get(i);
                if(!Files.isRegularFile(snapshot.storedPdf()) || !stored.location(snapshot.documentId()).equals(destinations.get(i)))throw new AssertionError("Wrong destination: "+snapshot);
                if(calls.contains(snapshot.storedPdf().getParent())!=(i==1))throw new AssertionError("Auto-generation setting ignored");
            }
            Path retained=snapshots.get(0).storedPdf().getParent().resolve("generated/keep.json");Files.createDirectories(retained.getParent());Files.writeString(retained,"preserve");
            PdfLibraryOrganization.placeImportedDocument(root,snapshots.get(0).documentId(),second.id());
            if(!Files.readString(retained).equals("preserve"))throw new AssertionError("Existing generated data changed");
            try {PdfLibraryOrganization.placeImportedDocument(root,snapshots.get(0).documentId(),"missing");throw new AssertionError("Deleted destination accepted");}
            catch(java.io.IOException expected){}
            if(!PdfLibraryOrganization.load(root).location(snapshots.get(0).documentId()).equals(second.id()))throw new AssertionError("Invalid destination changed placement");
        }
        System.out.println("PASS: per-file destinations, nested/home folders, mixed auto-generation, preserved data, stale destination rejection");
    }
}
