package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Fake transport proves cross-document scheduling without any remote calls. */
public final class PdfBatchSerialTest {
    public static void main(String[] args)throws Exception {
        Path directory=Files.createTempDirectory("batch-serial-");
        CountDownLatch locals=new CountDownLatch(6),firstRunning=new CountDownLatch(1),release=new CountDownLatch(1),lateLocal=new CountDownLatch(1);
        List<String> calls=new CopyOnWriteArrayList<>();
        AtomicInteger active=new AtomicInteger(),peak=new AtomicInteger();
        Map<Path,String> names=new ConcurrentHashMap<>();
        List<Path> files=new ArrayList<>();
        for(int n=1;n<=7;n++){
            Path path=directory.resolve("lesson-"+n+".pdf");
            try(PDDocument pdf=new PDDocument()){for(int j=0;j<n;j++)pdf.addPage(new PDPage());pdf.save(path.toFile());}
            files.add(path);
        }
        PdfBatchQueue.Runner runner=(process,script,arguments,events)->{
            Path folder=Path.of(arguments.get(arguments.indexOf("--folder")+1));
            String command=arguments.getFirst();
            if(command.equals("prepare")){
                try(PDDocument pdf=org.apache.pdfbox.Loader.loadPDF(folder.resolve("source.pdf").toFile())){names.put(folder,"lesson-"+pdf.getNumberOfPages()+".pdf");}
                Files.writeString(folder.resolve("document.json"),"{\"pages\":[]}");return;
            }
            Path request=Path.of(arguments.get(arguments.indexOf("--request")+1));
            Path result=request.resolveSibling(request.getFileName().toString().replace(".json",".result.json"));
            String name=names.get(folder);
            if(command.equals("prepare-study")){
                if(arguments.contains("--allow-remote"))throw new AssertionError("local preparation allowed API");
                if(name.equals("lesson-7.pdf"))lateLocal.countDown();else{locals.countDown();if(!locals.await(10,TimeUnit.SECONDS))throw new AssertionError("local preparation serialized");}
                if(name.equals("lesson-6.pdf")&&!firstRunning.await(10,TimeUnit.SECONDS))throw new AssertionError("first PDF waited for every local preparation");
                Files.writeString(result,"{}");return;
            }
            if(!arguments.contains("--allow-remote"))throw new AssertionError("unexpected remote phase");
            int count=active.incrementAndGet();peak.accumulateAndGet(count,Math::max);
            try{
                calls.add(command+":"+name);
                if(command.equals("group-plan")){
                    if(name.equals("lesson-3.pdf"))throw new java.io.IOException("simulated planning failure");
                    Files.writeString(result,"{\"totalCostEstimateUsd\":0.01}");
                }else if(command.equals("generate")){
                    if(name.equals("lesson-1.pdf")){firstRunning.countDown();if(!release.await(10,TimeUnit.SECONDS))throw new AssertionError("release timed out");}
                    Files.writeString(result,"{\"kind\":\"ai_generated\",\"incompleteStudyPages\":[]}");
                }else throw new AssertionError(command);
            }finally{active.decrementAndGet();}
        };
        try(PdfBatchQueue queue=new PdfBatchQueue(directory.resolve("library"),plans->{throw new AssertionError("production approval path changed");},ignored->{},()->{},true,runner)){
            List<Path> shuffled=new ArrayList<>(files.subList(0,6));Collections.reverse(shuffled);queue.submit(shuffled);
            if(!firstRunning.await(15,TimeUnit.SECONDS))throw new AssertionError("first PDF never started: "+queue.snapshots());
            if(!calls.equals(List.of("group-plan:lesson-1.pdf","generate:lesson-1.pdf")))throw new AssertionError("later PDF entered AI early: "+calls);
            queue.submit(List.of(files.get(6)));
            if(!lateLocal.await(10,TimeUnit.SECONDS))throw new AssertionError("later upload local preparation waited for AI");
            release.countDown();
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(15);
            while(queue.snapshots().stream().anyMatch(s->Set.of(PdfBatchQueue.State.PREPARING,PdfBatchQueue.State.QUEUED,PdfBatchQueue.State.RUNNING).contains(s.state()))&&System.nanoTime()<deadline)Thread.sleep(10);
            List<String> expected=new ArrayList<>();
            for(int n=1;n<=7;n++){expected.add("group-plan:lesson-"+n+".pdf");if(n!=3)expected.add("generate:lesson-"+n+".pdf");}
            if(!calls.equals(expected)||peak.get()!=1)throw new AssertionError("AI ordering/overlap: "+calls+" peak="+peak);
            if(queue.snapshots().get(2).state()!=PdfBatchQueue.State.FAILED||queue.snapshots().get(6).state()!=PdfBatchQueue.State.COMPLETE)throw new AssertionError("failed file blocked later files: "+queue.snapshots());
        }finally{release.countDown();try(var paths=Files.walk(directory)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}}
        System.out.println("PASS: six parallel local preparations, sorted serial AI, later-upload prefetch, failure continuation; no paid calls.");System.exit(0);
    }
}
