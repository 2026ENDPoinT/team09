package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Actual native dispatcher/transactions, fake UI, disposable PDFs; no live library or API. */
public final class AssistantTrashTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static JsonObject json(String text){return JsonParser.parseString(text).getAsJsonObject();}
    private static final class Ui implements AssistantLibraryUi {
        String folder="";int prepared,finished;
        public JsonObject viewContext(){JsonObject out=json("{\"screen\":\"library\",\"libraryVisible\":true,\"search\":\"\",\"visibleItems\":[]}");out.addProperty("currentFolderId",folder);return out;}
        public CompletionStage<JsonObject> navigateFolder(String id){folder=id;return CompletableFuture.completedFuture(new JsonObject());}
        public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(new JsonObject());}
        public Object prepareMutation(JsonArray changes){prepared++;return new Object();}
        public CompletionStage<JsonObject> finishMutation(Object ticket,JsonObject result){finished++;return CompletableFuture.completedFuture(result);}
    }
    private static JsonObject call(AssistantLocal host,String tool,JsonObject args,String quote){
        JsonObject request=new JsonObject();request.addProperty("id","test");request.addProperty("tool",tool);request.add("arguments",args);request.addProperty("authorizationQuote",quote);return host.handle(request);
    }
    private static JsonObject ok(JsonObject result){check(result.get("ok").getAsBoolean(),result.toString());return result.getAsJsonObject("data");}
    private static void begin(AssistantLocal host,String turn,String question,String source,String operation){
        host.begin("s",turn,question);JsonObject intent=json("{\"decision\":\"request\",\"operations\":[],\"sourceScope\":\"all\",\"proposalId\":\"\",\"clarificationId\":\"\",\"selectionAll\":false}");
        intent.addProperty("question",question);intent.addProperty("evidence",question);intent.addProperty("sourceScope",source);intent.getAsJsonArray("operations").add(operation);ok(call(host,"internal.libraryIntent",intent,""));
    }
    private static JsonObject command(AssistantLocal host,String... refs){
        JsonObject query=json("{\"parentId\":null}");ok(call(host,"library.query",query,""));
        JsonObject context=ok(call(host,"context.get",new JsonObject(),""));
        JsonObject out=new JsonObject();out.add("expectedRevision",context.getAsJsonObject("library").get("revision"));JsonArray ids=new JsonArray();
        for(int i=0;i<refs.length;i+=2){JsonObject ref=new JsonObject();ref.addProperty("kind",refs[i]);ref.addProperty("id",refs[i+1]);ids.add(ref);}out.add("ids",ids);return out;
    }
    private static String doc(Path root,char digit)throws Exception{
        String id=String.valueOf(digit).repeat(64);Path dir=root.resolve(id);Files.createDirectories(dir.resolve("generated"));Files.createDirectories(dir.resolve("requests"));
        Files.writeString(dir.resolve("source.pdf"),"%PDF preserved "+digit);Files.writeString(dir.resolve("generated/data.json"),"generated");Files.writeString(dir.resolve("requests/history.json"),"chat");return id;
    }
    private static void refused(JsonObject result,String code){check(!result.get("ok").getAsBoolean()&&result.get("code").getAsString().equals(code),result.toString());}
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-trash-");
        try{
            String a=doc(root,'a'),b=doc(root,'b'),c=doc(root,'c');var org=PdfLibraryOrganization.load(root);
            var parent=org.createFolder("","과제");var child=org.createFolder(parent.id(),"실습");org.moveDocument(a,child.id());
            var library=new AssistantLibrary(root);Ui ui=new Ui();AssistantLocal host=new AssistantLocal(new dev.synesis.poc.planner.PlannerStore(root.resolve("planner.json")),root.resolve("memory.json"),JsonObject::new);host.attachLibrary(library,ui);
            check(org.folder(PdfLibraryOrganization.TRASH_ID)==null,"fixture starts without trash");
            host.begin("s","no-grant","과제 삭제해줘");JsonObject noGrant=command(host,"folder",parent.id());refused(call(host,"library.trash",noGrant,"과제 삭제해줘"),"library_permission_required");
            check(ui.prepared==0,"ungranted trash prepared UI");
            begin(host,"batch","과제 폴더와 실습 폴더, a 파일, b 파일 삭제해줘","all","trash");
            JsonObject args=command(host,"folder",child.id(),"document",a,"folder",parent.id(),"document",b);String quote="과제 폴더와 실습 폴더, a 파일, b 파일 삭제해줘";
            JsonObject result=ok(call(host,"library.trash",args,quote));check(result.get("trashedCount").getAsInt()==4,"wrong selected count");check(result.getAsJsonArray("moved").size()==2,"nested selection flattened");
            org=PdfLibraryOrganization.load(root);check(org.folder(parent.id()).parentId().equals(PdfLibraryOrganization.TRASH_ID),"parent not trashed");check(org.folder(child.id()).parentId().equals(parent.id())&&org.location(a).equals(child.id()),"subtree not preserved");check(org.location(b).equals(PdfLibraryOrganization.TRASH_ID)&&org.location(c).isEmpty(),"unrelated doc moved");
            check(Files.readString(root.resolve(a).resolve("source.pdf")).equals("%PDF preserved a")&&Files.readString(root.resolve(a).resolve("generated/data.json")).equals("generated")&&Files.readString(root.resolve(a).resolve("requests/history.json")).equals("chat"),"trash physically deleted data");
            ok(call(host,"library.trash",args,quote));check(ui.finished==1,"transport replay moved twice");
            check(ok(call(host,"library.query",json("{\"kind\":\"document\"}"),"")).get("total").getAsInt()==1,"global query exposes trash documents");
            ui.folder=child.id();begin(host,"manual","여기 있는 파일 삭제해줘","current","trash");
            JsonObject explicit=ok(call(host,"library.query",json("{\"parentId\":\""+child.id()+"\"}"),""));JsonObject manual=command(host,"document",a);manual.add("expectedRevision",explicit.get("revision"));
            check(ok(call(host,"context.get",new JsonObject(),"")).getAsJsonObject("library").get("currentFolderInTrash").getAsBoolean(),"nested trash context missing");
            String revision=library.snapshot().get("revision").getAsString();int prepared=ui.prepared;
            JsonObject blocked=call(host,"library.trash",manual,"여기 있는 파일 삭제해줘");refused(blocked,"library_manual_delete_required");check(blocked.get("error").getAsString().contains("직접"),"manual deletion guidance missing");check(ui.prepared==prepared&&library.snapshot().get("revision").getAsString().equals(revision),"refused operation mutated state");
            ui.folder="";begin(host,"mixed","a와 c 모두 삭제해줘","all","trash");JsonObject mixed=command(host,"document",c,"document",a); // Observe trashed a explicitly; global search deliberately excludes it.
            ok(call(host,"library.query",json("{\"parentId\":\""+child.id()+"\"}"),""));refused(call(host,"library.trash",mixed,"a와 c 모두 삭제해줘"),"library_manual_delete_required");check(PdfLibraryOrganization.load(root).location(c).isEmpty(),"mixed rejection partially moved normal item");
            begin(host,"root","휴지통 삭제해줘","all","trash");refused(call(host,"library.trash",command(host,"folder",PdfLibraryOrganization.TRASH_ID),"휴지통 삭제해줘"),"library_manual_delete_required");
            begin(host,"stale","c 삭제해줘","all","trash");JsonObject stale=command(host,"document",c);PdfLibraryOrganization.load(root).createFolder("","새자료");refused(call(host,"library.trash",stale,"c 삭제해줘"),"library_stale");check(PdfLibraryOrganization.load(root).location(c).isEmpty(),"stale request moved c");
            begin(host,"wrong-operation","c 이름을 고쳐줘","all","rename");refused(call(host,"library.trash",command(host,"document",c),"c 이름을 고쳐줘"),"library_permission_required");
            check(!AssistantLibraryActions.supports("library.delete")&&!AssistantLibraryActions.supports("library.permanentlyDelete"),"permanent deletion capability exposed");
            // Storage layer remains safe even if invoked without the assistant guard.
            JsonArray nativeChanges=new JsonArray();nativeChanges.add(json("{\"operation\":\"trash\",\"kind\":\"document\",\"id\":\""+c+"\"}"));nativeChanges.add(json("{\"operation\":\"trash\",\"kind\":\"document\",\"id\":\""+a+"\"}"));
            try{library.apply("d".repeat(64),library.snapshot().get("revision").getAsString(),nativeChanges);throw new AssertionError("native guard missing");}catch(java.io.IOException expected){checks++;}
            check(PdfLibraryOrganization.load(root).location(c).isEmpty()&&Files.exists(root.resolve(a).resolve("source.pdf")),"native rejection wrote partial state");
            System.out.println("AssistantTrashTest passed: "+checks+" dispatcher, authorization, preservation, subtree, replay and manual-only delete checks");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
