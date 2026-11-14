package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.nio.file.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import javax.swing.SwingUtilities;

/** Deterministic offline lifecycle checks; no Python, paid calls or application window. */
public final class QuizBackgroundJobsTest {
    public static void main(String[] args)throws Exception {
        navigationDoesNotOwnTheJob();
        perDocumentJobsAndDeletion();
        System.out.println("QuizBackgroundJobsTest passed: tab/home visibility and study cancellation independence, per-PDF deduplication, durable completion and deletion guards. No paid calls.");
        System.exit(0);
    }
    private static void navigationDoesNotOwnTheJob()throws Exception {
        Path root=Files.createTempDirectory("quiz-background-");
        AtomicReference<PdfWorkspace> view=new AtomicReference<>();
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),done=new CountDownLatch(1);
        AtomicReference<Exception> failure=new AtomicReference<>();
        try {
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace workspace=new PdfWorkspace(false,root);view.set(workspace);
                QuizBackgroundJobs jobs=(QuizBackgroundJobs)get(workspace,"backgroundQuizzes");
                require(jobs.start("original-pdf",runner->{
                    entered.countDown();require(release.await(5,TimeUnit.SECONDS),"release timeout");
                    Files.writeString(root.resolve("completed.json"),"saved to original PDF");return new JsonObject();
                },(result,error)->{failure.set(error);done.countDown();}),"initial job starts");
                workspace.showSummary();workspace.showConceptSummary();workspace.showLearningTab("퀴즈로 학습하기");
                workspace.setVisible(false); // Home hides the workspace instead of owning its workers.
                ((AtomicInteger)get(workspace,"generation")).incrementAndGet();
                ((PdfProcess)get(workspace,"processes")).cancel(); // Same path used when another PDF opens.
                require(jobs.running("original-pdf"),"navigation must not cancel document job");
                require(workspace.hasBackgroundQuizGeneration(),"application must retain this workspace when another PDF opens");
            });
            require(entered.await(5,TimeUnit.SECONDS),"worker starts");release.countDown();
            require(done.await(5,TimeUnit.SECONDS),"hidden worker completes");
            require(failure.get()==null&&Files.exists(root.resolve("completed.json")),"original result survives navigation");
        }finally{
            release.countDown();if(view.get()!=null)SwingUtilities.invokeAndWait(view.get()::close);
            try(var files=Files.walk(root)){for(Path p:files.sorted(java.util.Comparator.reverseOrder()).toList())Files.delete(p);}
        }
    }
    private static void perDocumentJobsAndDeletion()throws Exception {
        QuizBackgroundJobs jobs=new QuizBackgroundJobs();
        CountDownLatch entered=new CountDownLatch(2),release=new CountDownLatch(1),done=new CountDownLatch(2);
        try {
            QuizBackgroundJobs.Work work=runner->{entered.countDown();require(release.await(5,TimeUnit.SECONDS),"release timeout");return new JsonObject();};
            require(jobs.start("a",work,(r,e)->done.countDown()),"PDF A starts");
            require(!jobs.start("a",work,(r,e)->{}),"same PDF cannot be charged twice by a repeated click");
            require(jobs.start("b",work,(r,e)->done.countDown()),"PDF B has its own job");
            require(entered.await(5,TimeUnit.SECONDS),"both PDFs can progress");
            CompletableFuture<Void> cancelled=jobs.cancel("a");
            require(!jobs.publicationAllowed("a")&&jobs.publicationAllowed("b"),"deleting A does not invalidate B");
            release.countDown();cancelled.get(5,TimeUnit.SECONDS);require(done.await(5,TimeUnit.SECONDS),"workers drain");
            require(!jobs.running("a")&&!jobs.running("b"),"completed jobs release their state");
        }finally{release.countDown();jobs.close();}
    }
    private static Object get(Object owner,String name){try{var field=owner.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(owner);}catch(Exception e){throw new RuntimeException(e);}}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
