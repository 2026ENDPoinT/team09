package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import javax.swing.SwingUtilities;

/** Source-only contract replay. No native window, build, network or app data required. */
public final class AssistantLibraryNavigationTest {
    static void check(boolean value,String label){if(!value)throw new AssertionError(label);}
    private static final class Ui implements AssistantLibraryUi {
        final AtomicInteger opens=new AtomicInteger(),folders=new AtomicInteger(),cancelled=new AtomicInteger();
        java.util.function.Consumer<String> onOpen=id->{};
        public JsonObject viewContext(){
            check(SwingUtilities.isEventDispatchThread(),"view snapshot must share the screen-state EDT hop");
            JsonObject out=new JsonObject();out.addProperty("libraryVisible",true);out.addProperty("screen","library");out.addProperty("section","library");out.addProperty("currentFolderId","folder1");return out;
        }
        public CompletionStage<JsonObject> navigateFolder(String id){folders.incrementAndGet();return CompletableFuture.completedFuture(new JsonObject());}
        public CompletionStage<JsonObject> openDocument(String id){opens.incrementAndGet();onOpen.accept(id);JsonObject result=new JsonObject();result.addProperty("status","opened");result.addProperty("id",id);return CompletableFuture.completedFuture(result);}
        public Object prepareMutation(JsonArray changes){check(!SwingUtilities.isEventDispatchThread(),"preparation must not block event thread");return changes;}
        public void cancelMutation(Object ticket){cancelled.incrementAndGet();}
        public CompletionStage<JsonObject> finishMutation(Object ticket,JsonObject result){return CompletableFuture.completedFuture(result);}
    }
    public static void main(String[] args)throws Exception{
        Ui ui=new Ui();AtomicBoolean visible=new AtomicBoolean(false);AtomicInteger reveals=new AtomicInteger();AtomicReference<String> active=new AtomicReference<>("active-document");
        AssistantLibraryNavigation bridge=new AssistantLibraryNavigation(ui,()->{check(SwingUtilities.isEventDispatchThread(),"screen state only on EDT");return visible.get();},active::get,()->{check(SwingUtilities.isEventDispatchThread(),"normal reveal on EDT");reveals.incrementAndGet();visible.set(true);});
        JsonObject view=bridge.viewContext();check(view.get("screen").getAsString().equals("study")&&!view.get("libraryVisible").getAsBoolean(),"study snapshot is not hidden folder screen");
        check(view.get("currentDocumentId").getAsString().equals("active-document"),"current PDF identity");
        JsonObject already=bridge.openDocument("active-document").toCompletableFuture().get(3,TimeUnit.SECONDS);
        check(already.get("status").getAsString().equals("already_open")&&reveals.get()==0&&ui.opens.get()==0,"already-open study document preserves screen");
        bridge.navigateFolder("parent").toCompletableFuture().get(3,TimeUnit.SECONDS);check(reveals.get()==1&&ui.folders.get()==1,"reveal before folder navigation");
        CountDownLatch clicked=new CountDownLatch(1);ui.onOpen=id->clicked.countDown();
        CompletableFuture<JsonObject> opening=bridge.openDocument("other-document").toCompletableFuture();
        check(clicked.await(1,TimeUnit.SECONDS),"native click callback started");
        check(!opening.isDone(),"click completion alone must not report the new study screen ready");
        SwingUtilities.invokeAndWait(()->{javax.swing.Timer transition=new javax.swing.Timer(50,event->{active.set("other-document");visible.set(false);});transition.setRepeats(false);transition.start();});
        check(opening.get(3,TimeUnit.SECONDS).get("id").getAsString().equals("other-document"),"completed after matching document is displayed");
        check(bridge.viewContext().get("screen").getAsString().equals("study")&&bridge.viewContext().get("currentDocumentId").getAsString().equals("other-document"),"subsequent scope snapshot sees the completed study transition");
        check(ui.opens.get()==1&&reveals.get()==1,"no redundant reveal");
        JsonArray changes=new JsonArray();Object prepared=bridge.prepareMutation(changes);
        check(!visible.get()&&reveals.get()==1,"mutation captures available visuals without leaving the current study screen");
        bridge.cancelMutation(prepared);check(ui.cancelled.get()==1,"failed mutation capture cleanup forwarded");
        AssistantLibraryNavigation failing=new AssistantLibraryNavigation(ui,()->{throw new IllegalStateException("fixture");},()->null,()->{});
        try{failing.openDocument("anything").toCompletableFuture().get(3,TimeUnit.SECONDS);throw new AssertionError("supplier failure reported success");}catch(ExecutionException expected){}
        timeoutAndCancellation();
        System.out.println("AssistantLibraryNavigationTest OK: atomic view, async document handoff, existing document, failure, timeout and cancellation cleanup");
    }
    private static void timeoutAndCancellation()throws Exception{
        Ui idle=new Ui();AtomicInteger reads=new AtomicInteger();
        AssistantLibraryNavigation timeout=new AssistantLibraryNavigation(idle,()->{reads.incrementAndGet();return true;},()->null,()->{},120);
        try{timeout.openDocument("never-visible").toCompletableFuture().get(2,TimeUnit.SECONDS);throw new AssertionError("unfinished transition reported success");}
        catch(ExecutionException expected){check(expected.getCause() instanceof java.io.IOException,"bounded timeout is a meaningful navigation failure");}
        int afterTimeout=reads.get();Thread.sleep(120);SwingUtilities.invokeAndWait(()->{});check(reads.get()==afterTimeout,"timeout stops temporary polling timer");

        Ui cancelledUi=new Ui();AtomicInteger cancelReads=new AtomicInteger();CountDownLatch called=new CountDownLatch(1);cancelledUi.onOpen=id->called.countDown();
        AssistantLibraryNavigation cancellation=new AssistantLibraryNavigation(cancelledUi,()->{cancelReads.incrementAndGet();return true;},()->null,()->{},1000);
        CompletableFuture<JsonObject> pending=cancellation.openDocument("cancelled").toCompletableFuture();check(called.await(1,TimeUnit.SECONDS),"cancellation fixture clicked");
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);while(cancelReads.get()<3&&System.nanoTime()<deadline)Thread.sleep(5);
        check(pending.cancel(false),"pending handoff can be canceled");SwingUtilities.invokeAndWait(()->{});
        int afterCancel=cancelReads.get();Thread.sleep(120);SwingUtilities.invokeAndWait(()->{});check(cancelReads.get()==afterCancel,"cancellation stops temporary polling timer");

        Ui failureUi=new Ui();AtomicBoolean fail=new AtomicBoolean();failureUi.onOpen=id->fail.set(true);
        AssistantLibraryNavigation supplierFailure=new AssistantLibraryNavigation(failureUi,()->{if(fail.get())throw new IllegalStateException("after-click fixture");return true;},()->null,()->{},1000);
        try{supplierFailure.openDocument("failed").toCompletableFuture().get(2,TimeUnit.SECONDS);throw new AssertionError("handoff supplier failure reported success");}
        catch(ExecutionException expected){check(expected.getCause() instanceof IllegalStateException,"handoff failures complete the future");}
    }

}
