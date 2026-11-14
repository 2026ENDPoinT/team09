package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.util.concurrent.*;
import java.util.function.BiConsumer;

/** Document-owned jobs, independent of visible tabs and the study worker's cancellation epoch. */
final class QuizBackgroundJobs implements AutoCloseable {
    interface Work {JsonObject run(PdfProcess process)throws Exception;}
    private record Job(PdfProcess process,CompletableFuture<Void> done) {}
    private final ConcurrentHashMap<String,Job> active=new ConcurrentHashMap<>();
    private final java.util.Set<String> removed=ConcurrentHashMap.newKeySet();
    private static final ExecutorService WORKERS=Executors.newFixedThreadPool(2,task->{
        Thread thread=new Thread(task,"quiz-background");thread.setDaemon(true);return thread;
    });
    private boolean closed;
    boolean running(String documentId){return active.containsKey(documentId);}
    boolean running(){return !active.isEmpty();}
    boolean publicationAllowed(String documentId){return !removed.contains(documentId);}
    synchronized boolean start(String documentId,Work work,BiConsumer<JsonObject,Exception> completed) {
        if(closed)return false;
        Job job=new Job(new PdfProcess(),new CompletableFuture<>());
        if(active.putIfAbsent(documentId,job)!=null)return false;
        removed.remove(documentId);
        WORKERS.execute(()->{
            JsonObject result=null;Exception failure=null;
            try {result=work.run(job.process());}catch(Exception error){failure=error;}
            finally {
                job.process().close();
                CompletableFuture<Void> workerIdle=new CompletableFuture<>();
                job.process().afterIdle(()->workerIdle.complete(null));
                workerIdle.join();
                active.remove(documentId,job);
            }
            try {completed.accept(result,failure);}finally{job.done().complete(null);}
        });
        return true;
    }
    CompletableFuture<Void> cancel(String documentId) {
        removed.add(documentId);
        Job job=active.get(documentId);
        if(job==null)return CompletableFuture.completedFuture(null);
        job.process().close();return job.done();
    }
    synchronized CompletableFuture<Void> closeAndAwait() {
        closed=true;
        var jobs=java.util.List.copyOf(active.values());
        jobs.forEach(job->job.process().close());
        return CompletableFuture.allOf(jobs.stream().map(Job::done).toArray(CompletableFuture[]::new));
    }
    @Override public void close(){closeAndAwait();}
}
