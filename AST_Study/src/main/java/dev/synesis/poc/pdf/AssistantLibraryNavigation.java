package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.io.IOException;
import java.util.concurrent.*;
import java.util.function.*;
import javax.swing.SwingUtilities;

/** Reuses the application's screen navigation for library operations. */
public final class AssistantLibraryNavigation implements AssistantLibraryUi {
    private final AssistantLibraryUi library;
    private final BooleanSupplier libraryVisible;
    private final Supplier<String> currentDocument;
    private final Runnable revealLibrary;
    private final long openTimeoutNanos;
    public AssistantLibraryNavigation(AssistantLibraryUi library,BooleanSupplier libraryVisible,Supplier<String> currentDocument,Runnable revealLibrary){this(library,libraryVisible,currentDocument,revealLibrary,18_000);}
    AssistantLibraryNavigation(AssistantLibraryUi library,BooleanSupplier libraryVisible,Supplier<String> currentDocument,Runnable revealLibrary,long openTimeoutMillis){
        if(openTimeoutMillis<=0)throw new IllegalArgumentException("파일 전환 대기 시간을 확인해 주세요.");
        this.library=library;this.libraryVisible=libraryVisible;this.currentDocument=currentDocument;this.revealLibrary=revealLibrary;this.openTimeoutNanos=TimeUnit.MILLISECONDS.toNanos(openTimeoutMillis);
    }
    @Override public JsonObject viewContext() throws Exception {
        return onEdt(()->{JsonObject context=library.viewContext();boolean visible=libraryVisible.getAsBoolean();context.addProperty("libraryVisible",visible&&context.has("libraryVisible")&&context.get("libraryVisible").getAsBoolean());
            if(!visible)context.addProperty("screen","study");String document=currentDocument.get();if(document!=null)context.addProperty("currentDocumentId",document);return context;});
    }
    private CompletableFuture<Void> reveal(){
        CompletableFuture<Void> result=new CompletableFuture<>();
        SwingUtilities.invokeLater(()->{
            try{
                if(result.isDone())return;
                if(libraryVisible.getAsBoolean()){result.complete(null);return;}
                revealLibrary.run();
                if(libraryVisible.getAsBoolean()){result.complete(null);return;}
                long started=System.nanoTime();javax.swing.Timer timer=new javax.swing.Timer(50,null);
                timer.addActionListener(event->{
                    if(result.isDone()){timer.stop();return;}
                    if(libraryVisible.getAsBoolean()){timer.stop();result.complete(null);}
                    else if(System.nanoTime()-started>10_000_000_000L){timer.stop();result.completeExceptionally(new IOException("현재 작업을 보존하기 위해 자료 화면 전환을 마치지 않았어요."));}
                });timer.start();
            }catch(Exception failure){result.completeExceptionally(failure);}
        });return result;
    }
    @Override public CompletionStage<JsonObject> navigateFolder(String id){return reveal().thenCompose(ignored->library.navigateFolder(id));}
    @Override public CompletionStage<JsonObject> openDocument(String id){
        CompletableFuture<JsonObject> result=new CompletableFuture<>();long deadline=System.nanoTime()+openTimeoutNanos;
        SwingUtilities.invokeLater(()->{try{
            if(result.isDone())return;
            if(!libraryVisible.getAsBoolean()&&id.equals(currentDocument.get())){JsonObject out=new JsonObject();out.addProperty("status","already_open");out.addProperty("id",id);result.complete(out);return;}
            CompletableFuture<Void> shown=reveal();
            result.whenComplete((value,failure)->{if(result.isCancelled())shown.cancel(false);});
            shown.thenCompose(ignored->{
                if(result.isDone())return CompletableFuture.<JsonObject>failedFuture(new CancellationException("파일 열기를 취소했어요."));
                CompletableFuture<JsonObject> opened=library.openDocument(id).toCompletableFuture();
                result.whenComplete((value,failure)->{if(result.isCancelled())opened.cancel(false);});
                return opened;
            }).whenComplete((value,failure)->{
                if(failure!=null)result.completeExceptionally(failure);
                else awaitDocument(id,value,deadline,result);
            });
        }catch(Exception failure){result.completeExceptionally(failure);}});return result;
    }
    /** The click callback starts LibraryDeparture; it does not mean the new PDF is visible yet. */
    private void awaitDocument(String id,JsonObject opened,long deadline,CompletableFuture<JsonObject> result){
        SwingUtilities.invokeLater(()->{
            if(result.isDone())return;
            javax.swing.Timer timer=new javax.swing.Timer(50,null);
            Runnable check=()->{
                if(result.isDone()){timer.stop();return;}
                try{
                    if(!libraryVisible.getAsBoolean()&&id.equals(currentDocument.get())){timer.stop();result.complete(opened);}
                    else if(System.nanoTime()>=deadline){timer.stop();result.completeExceptionally(new IOException("파일 열기를 시작했지만 학습 화면 전환 완료를 확인하지 못했어요. 현재 화면을 확인해 주세요."));}
                }catch(Exception failure){timer.stop();result.completeExceptionally(failure);}
            };
            timer.addActionListener(event->check.run());timer.setCoalesce(true);
            result.whenComplete((value,failure)->{if(SwingUtilities.isEventDispatchThread())timer.stop();else SwingUtilities.invokeLater(timer::stop);});
            check.run();if(!result.isDone())timer.start();
        });
    }
    @Override public Object prepareMutation(JsonArray changes)throws Exception {
        if(SwingUtilities.isEventDispatchThread())throw new IllegalStateException("파일 저장 작업은 화면 스레드에서 실행하지 않아요.");
        // Saving uses stable library IDs. The user's current screen only decides
        // whether a transient move animation can be captured, never permission.
        return library.prepareMutation(changes);
    }
    @Override public void cancelMutation(Object prepared){library.cancelMutation(prepared);}
    @Override public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){return library.finishMutation(prepared,result);}
    private static <T>T onEdt(Callable<T> action)throws Exception {
        if(SwingUtilities.isEventDispatchThread())return action.call();FutureTask<T> task=new FutureTask<>(action);SwingUtilities.invokeAndWait(task);return task.get();
    }
}
