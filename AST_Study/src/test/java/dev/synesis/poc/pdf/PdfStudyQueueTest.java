package dev.synesis.poc.pdf;

import org.apache.pdfbox.pdmodel.*;
import javax.swing.SwingUtilities;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;

/** Real workspace admission + fake upload transport; no provider or user data. */
public final class PdfStudyQueueTest {
    static Object field(Object value,String name)throws Exception {Field f=value.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(value);}
    static void field(Object value,String name,Object content)throws Exception {Field f=value.getClass().getDeclaredField(name);f.setAccessible(true);f.set(value,content);}
    static void edt(Runnable action)throws Exception {SwingUtilities.invokeAndWait(action);}
    static void await(BooleanSupplier condition)throws Exception {
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        while(!condition.getAsBoolean()&&System.nanoTime()<until)Thread.sleep(5);
        check(condition.getAsBoolean(),"Timed out");
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void finish(PdfWorkspace view)throws Exception {
        Method m=PdfWorkspace.class.getDeclaredMethod("finishGeneration",boolean.class,String.class);m.setAccessible(true);
        edt(()->{try {m.invoke(view,false,"테스트 완료");}catch(Exception e){throw new RuntimeException(e);}});
    }
    static PdfWorkspace workspace(Path pdf,Path library)throws Exception {
        PdfSource source=PdfSource.open(pdf,library);PdfWorkspace[] answer={null};
        edt(()->answer[0]=new PdfWorkspace(false,library));field(answer[0],"source",source);return answer[0];
    }
    public static void main(String[] args)throws Exception {
        Path temp=Files.createTempDirectory("study-global-queue-");
        Path library=temp.resolve("library");List<Path> files=new ArrayList<>();
        for(int i=1;i<=4;i++) {
            Path pdf=temp.resolve("lesson-"+i+".pdf");
            try(PDDocument doc=new PDDocument()){for(int j=0;j<i;j++)doc.addPage(new PDPage());doc.save(pdf.toFile());}
            files.add(pdf);
        }
        PdfWorkspace first=workspace(files.get(0),library),second=workspace(files.get(1),library),cancelled=workspace(files.get(3),library);
        CountDownLatch firstReady=new CountDownLatch(1),secondReady=new CountDownLatch(1),batchRunning=new CountDownLatch(1),releaseBatch=new CountDownLatch(1);
        List<String> calls=new CopyOnWriteArrayList<>();
        PdfBatchQueue.Runner runner=(process,script,arguments,events)->{
            String command=arguments.getFirst();Path folder=Path.of(arguments.get(arguments.indexOf("--folder")+1));
            if(command.equals("prepare")){Files.writeString(folder.resolve("document.json"),"{\"pages\":[]}");return;}
            Path request=Path.of(arguments.get(arguments.indexOf("--request")+1));
            Path result=request.resolveSibling(request.getFileName().toString().replace(".json",".result.json"));
            if(command.equals("prepare-study")){Files.writeString(result,"{}");return;}
            calls.add(command);
            if(command.equals("group-plan"))Files.writeString(result,"{\"totalCostEstimateUsd\":0.01}");
            else {batchRunning.countDown();check(releaseBatch.await(10,TimeUnit.SECONDS),"Upload release timed out");Files.writeString(result,"{\"kind\":\"ai_generated\",\"incompleteStudyPages\":[]}");}
        };
        Path releaseWorker=temp.resolve("release-worker");
        Path script=temp.resolve("local_worker.py");
        Files.writeString(script,"import json,pathlib,sys,time\nprint(json.dumps({'type':'ready'}),flush=True)\nwhile not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)\n");
        try(PdfBatchQueue batch=new PdfBatchQueue(library,plans->{throw new AssertionError("No approval expected");},ignored->{},()->{},true,runner)) {
            edt(()->first.admitStudyGeneration(()->{calls.add("existing-1");firstReady.countDown();}));
            check(firstReady.await(10,TimeUnit.SECONDS),"Existing file did not start");
            PdfProcess process=(PdfProcess)field(first,"processes");CountDownLatch workerReady=new CountDownLatch(1);
            CompletableFuture<Void> worker=CompletableFuture.runAsync(()->{
                try {process.run(script.toString(),List.of(releaseWorker.toString()),process.ticket(),event->workerReady.countDown());}
                catch(Exception e){throw new CompletionException(e);}
            });
            check(workerReady.await(10,TimeUnit.SECONDS),"Local worker did not start");
            batch.submit(List.of(files.get(2)));
            await(()->PdfStudyQueue.global().waitingCount()==1);
            edt(()->second.admitStudyGeneration(()->{calls.add("existing-2");secondReady.countDown();}));
            await(()->PdfStudyQueue.global().waitingCount()==2);
            edt(()->cancelled.admitStudyGeneration(()->{throw new AssertionError("Cancelled pending file started");}));
            await(()->PdfStudyQueue.global().waitingCount()==3);
            edt(cancelled::close);await(()->PdfStudyQueue.global().waitingCount()==2);
            check(calls.equals(List.of("existing-1")),"Another file entered while the first file owned admission");
            finish(first);
            check(!batchRunning.await(150,TimeUnit.MILLISECONDS),"Admission released before the actual worker drained");
            Files.writeString(releaseWorker,"");worker.get(10,TimeUnit.SECONDS);
            check(batchRunning.await(10,TimeUnit.SECONDS),"Upload was blocked after old worker drained");
            check(!secondReady.await(100,TimeUnit.MILLISECONDS),"Workspace entered between upload planning and generation");
            check(calls.equals(List.of("existing-1","group-plan","generate")),"Wrong shared queue order: "+calls);
            releaseBatch.countDown();check(secondReady.await(10,TimeUnit.SECONDS),"Queued existing file did not resume");
            finish(second);
            check(calls.equals(List.of("existing-1","group-plan","generate","existing-2")),"Wrong final order: "+calls);
            await(()->PdfStudyQueue.global().waitingCount()==0);
        }finally {
            releaseBatch.countDown();Files.writeString(releaseWorker,"");
            edt(()->{first.close();second.close();cancelled.close();});
        }
        // Permit failure, interruption and duplicate cleanup cannot leak capacity.
        PdfStudyQueue gate=new PdfStudyQueue();var held=gate.acquire();
        Thread interrupted=new Thread(()->{try {gate.acquire().close();}catch(InterruptedException expected){}});
        interrupted.start();await(()->gate.waitingCount()==1);interrupted.interrupt();interrupted.join(2000);
        held.close();held.close();
        try(var next=gate.acquire()){check(!interrupted.isAlive(),"Interrupted waiter survived");}
        System.out.println("PdfStudyQueueTest passed: upload/existing FIFO, planning+generation lease, live-worker drain, queued cancellation and unchanged local preparation");
        System.exit(0);
    }
}
