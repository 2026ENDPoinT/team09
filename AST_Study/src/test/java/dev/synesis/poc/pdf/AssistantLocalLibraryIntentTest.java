package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Dispatcher/native integration on a disposable store, without an API or window. */
public final class AssistantLocalLibraryIntentTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static JsonObject json(String value){return JsonParser.parseString(value).getAsJsonObject();}
    private static JsonObject call(AssistantLocal host,String tool,JsonObject args,String quote){
        JsonObject request=new JsonObject();request.addProperty("id","test");request.addProperty("tool",tool);request.add("arguments",args);request.addProperty("authorizationQuote",quote);return host.handle(request);
    }
    private static JsonObject ok(JsonObject result){check(result.get("ok").getAsBoolean(),result.toString());return result.getAsJsonObject("data");}
    private static JsonObject context(AssistantLocal host){return ok(call(host,"context.get",new JsonObject(),""));}
    private static JsonObject intent(String question,String operation){
        JsonObject value=json("{\"decision\":\"request\",\"evidence\":\"\",\"operations\":[],\"sourceScope\":\"root\",\"proposalId\":\"\",\"clarificationId\":\"\",\"selectionAll\":false}");
        value.addProperty("question",question);value.addProperty("evidence",question);value.getAsJsonArray("operations").add(operation);return value;
    }
    private static final class Ui implements AssistantLibraryUi {
        int opened,finished;
        public JsonObject viewContext(){return json("{\"screen\":\"library\",\"libraryVisible\":true,\"currentFolderId\":\"\",\"search\":\"\",\"visibleItems\":[]}");}
        public CompletionStage<JsonObject> navigateFolder(String id){opened++;return CompletableFuture.completedFuture(json("{\"status\":\"opened\"}"));}
        public CompletionStage<JsonObject> openDocument(String id){opened++;return CompletableFuture.completedFuture(json("{\"status\":\"opened\"}"));}
        public Object prepareMutation(JsonArray changes){return new Object();}
        public void cancelMutation(Object prepared){}
        public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){finished++;return CompletableFuture.completedFuture(result);}
    }
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-native-intent-");
        try{
            var source=PdfLibraryOrganization.load(root).createFolder("","자료");
            var destination=PdfLibraryOrganization.load(root).createFolder("","보관함");
            AssistantLocal host=new AssistantLocal(new PlannerStore(root.resolve("planner.json")),root.resolve("preferences.json"),JsonObject::new);
            Ui ui=new Ui();host.attachLibrary(new AssistantLibrary(root),ui);
            String question="자료는 보관함으로 부탁할게요";
            host.begin("s","move",question);JsonObject before=context(host);
            check(before.getAsJsonObject("library").get("semanticAuthorization").getAsBoolean(),"native explicitly advertises semantic support");
            check(before.get("mutationScope").getAsString().isEmpty(),"words never create library permission before interpretation");
            JsonObject read=ok(call(host,"library.query",new JsonObject(),""));
            JsonObject move=new JsonObject();move.addProperty("expectedRevision",read.get("revision").getAsString());move.addProperty("destinationId",destination.id());
            JsonArray ids=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("kind","folder");ref.addProperty("id",source.id());ids.add(ref);move.add("ids",ids);
            check(!call(host,"library.proposeMove",move,question).get("ok").getAsBoolean(),"uninterpreted model tool cannot move");
            JsonObject decision=intent(question,"move");ok(call(host,"internal.libraryIntent",decision,""));
            JsonObject after=context(host);String quote=after.getAsJsonObject("library").get("authorizationQuote").getAsString();
            check(after.get("mutationScope").getAsString().equals("libraryWrite"),"native scope appears only after current evidence validated");
            check(after.get("authorizationQuote").getAsString().isEmpty(),"file grant cannot replace planner/memory quote");
            JsonObject applied=ok(call(host,"library.proposeMove",move,quote));check(applied.get("movedCount").getAsInt()==1,"clear request executes without second approval turn");
            check(PdfLibraryOrganization.load(root).folder(source.id()).parentId().equals(destination.id())&&ui.finished==1,"only selected item commits through existing UI adapter");
            ok(call(host,"internal.libraryIntent",decision,""));ok(call(host,"library.proposeMove",move,quote));check(ui.finished==1,"replayed interpretation and operation do not replay mutation");
            host.begin("s","next","내용이 궁금해요");check(context(host).get("mutationScope").getAsString().isEmpty(),"next turn does not inherit completed permission");
            JsonObject forged=intent("다른 사용자 메시지","move");check(!call(host,"internal.libraryIntent",forged,"").get("ok").getAsBoolean(),"dispatcher cannot authorize another message");
            host.begin("s","register-isolation","앞으로 나를 민수라고 불러");AssistantLocalTest.authorize(host,"앞으로 나를 민수라고 불러","memory");
            ok(call(host,"memory.update",json("{\"expectedRevision\":0,\"set\":{\"preferredName\":\"민수\"},\"remove\":[]}"),"앞으로 나를 민수라고 불러"));host.finish("저장했어요.");
            host.begin("s","library-routing","보관함 폴더 내용이 궁금해요");check(!context(host).get("recoveryInterpretationEligible").getAsBoolean(),"file turn does not need a separate undo classifier");
            host.begin("s","ordinary-routing","방금 부탁한 걸 원상태로 해주세요");check(context(host).get("recoveryInterpretationEligible").getAsBoolean(),"existing contextual planner/memory recovery remains available");
            System.out.println("AssistantLocalLibraryIntentTest OK · "+checks+" checks");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
