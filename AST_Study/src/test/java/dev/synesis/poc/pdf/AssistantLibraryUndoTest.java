package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.nio.file.attribute.FileTime;
import java.util.*;
import java.util.concurrent.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;

/** Unified latest-activity undo against actual dispatcher/stores; no API/live data/UI windows. */
public final class AssistantLibraryUndoTest {
    private static int count;
    private static void verify(boolean value,String message){count++;if(!value)throw new AssertionError(message);}
    private static final class Ui implements AssistantLibraryUi {
        int finishes;String folder="";
        public JsonObject viewContext(){JsonObject out=json("{\"screen\":\"library\",\"libraryVisible\":true,\"search\":\"\",\"visibleItems\":[]}");out.addProperty("currentFolderId",folder);return out;}
        public CompletionStage<JsonObject> navigateFolder(String id){folder=id;return CompletableFuture.completedFuture(new JsonObject());}
        public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(new JsonObject());}
        public Object prepareMutation(JsonArray changes){return new Object();}
        public CompletionStage<JsonObject> finishMutation(Object ignored,JsonObject data){finishes++;return CompletableFuture.completedFuture(data);}
    }
    private static JsonObject context(AssistantLocal host){return ok(call(host,"context.get",new JsonObject(),""));}
    private static String doc(Path root,char digit)throws Exception{
        String id=String.valueOf(digit).repeat(64);Path dir=root.resolve(id);Files.createDirectories(dir.resolve("generated"));Files.createDirectories(dir.resolve("requests"));
        Files.writeString(dir.resolve("source.pdf"),"%PDF "+digit);Files.writeString(dir.resolve("generated/answer.json"),"keep data");Files.writeString(dir.resolve("requests/history.json"),"keep history");Files.writeString(dir.resolve("library.properties"),"name="+digit+".pdf\n");return id;
    }
    private static void start(AssistantLocal host,String turn,String q,String... operations){
        host.begin("s",turn,q);JsonObject intent=json("{\"decision\":\"request\",\"operations\":[],\"sourceScope\":\"all\",\"proposalId\":\"\",\"clarificationId\":\"\",\"selectionAll\":false}");intent.addProperty("question",q);intent.addProperty("evidence",q);for(String op:operations)intent.getAsJsonArray("operations").add(op);ok(call(host,"internal.libraryIntent",intent,""));
    }
    private static String revision(AssistantLocal host){return ok(call(host,"library.query",new JsonObject(),"")).get("revision").getAsString();}
    private static JsonObject ids(String revision,String... refs){JsonObject out=new JsonObject();out.addProperty("expectedRevision",revision);JsonArray ids=new JsonArray();for(int i=0;i<refs.length;i+=2){JsonObject ref=new JsonObject();ref.addProperty("kind",refs[i]);ref.addProperty("id",refs[i+1]);ids.add(ref);}out.add("ids",ids);return out;}
    private static JsonObject undoArgs(AssistantLocal host){JsonObject out=new JsonObject();out.add("id",context(host).getAsJsonObject("undo").get("id"));return out;}
    private static void trash(AssistantLocal host,String turn,String q,String... refs){start(host,turn,q,"trash");ok(call(host,"library.trash",ids(revision(host),refs),q));host.finish("휴지통으로 옮겼어요.");}
    public static void main(String[] ignored)throws Exception{
        Path base=Files.createTempDirectory("unified-library-undo-"),root=base.resolve("library");Files.createDirectories(root);
        try{
            String a=doc(root,'a'),b=doc(root,'b'),c=doc(root,'c');var org=PdfLibraryOrganization.load(root);org.ensureTrashFolder();var parent=org.createFolder("","수업");var child=org.createFolder(parent.id(),"기출");org.moveDocument(a,child.id());org.moveDocument(b,parent.id());
            PlannerStore planner=new PlannerStore(base.resolve("planner.json"));Path memory=base.resolve("memory.json");Ui ui=new Ui();AssistantLocal host=new AssistantLocal(planner,memory,JsonObject::new);host.attachLibrary(new AssistantLibrary(root),ui);
            AssistantRecoveryIntentTest.seed(host,"old-planner");JsonObject oldPlannerUndo=undoArgs(host);var plannerBefore=planner.load();
            trash(host,"trash-batch","이 수업 폴더와 c 파일 삭제해줘","folder",parent.id(),"document",c);
            JsonObject info=context(host).getAsJsonObject("undo");verify(info.get("domain").getAsString().equals("library")&&info.get("available").getAsBoolean(),"old planner leaked after file mutation");verify(info.getAsJsonObject("context").get("request").getAsString().contains("수업 폴더"),"latest file request lost");
            host.begin("s","undo-trash","다시 되돌려줘");verify(context(host).get("recoveryInterpretationEligible").getAsBoolean(),"file undo interpretation not offered");JsonObject target=undoArgs(host);JsonObject recovered=ok(call(host,"actions.undo",target,"다시 되돌려줘"));verify(recovered.get("domain").getAsString().equals("library"),"wrong domain restored");
            org=PdfLibraryOrganization.load(root);verify(org.folder(parent.id()).parentId().isEmpty()&&org.folder(child.id()).parentId().equals(parent.id())&&org.location(a).equals(child.id())&&org.location(b).equals(parent.id())&&org.location(c).isEmpty(),"trash undo did not restore exact mixed locations");verify(planner.load().equals(plannerBefore),"unrelated planner changed");verify(Files.readString(root.resolve(a).resolve("generated/answer.json")).equals("keep data")&&Files.readString(root.resolve(a).resolve("requests/history.json")).equals("keep history"),"undo removed associated data");
            int finished=ui.finishes;ok(call(host,"actions.undo",target,"다시 되돌려줘"));verify(ui.finishes==finished,"undo retry replayed UI/storage mutation");
            host=new AssistantLocal(planner,memory,JsonObject::new);host.attachLibrary(new AssistantLibrary(root),ui);host.begin("s","undo-trash","다시 되돌려줘");ok(call(host,"actions.undo",target,"다시 되돌려줘"));
            host.begin("s","undo-again","한 번 더 되돌려줘");denied(call(host,"actions.undo",oldPlannerUndo,"한 번 더 되돌려줘"));verify(context(host).getAsJsonObject("undo").get("domain").getAsString().equals("library")&&!context(host).getAsJsonObject("undo").get("available").getAsBoolean(),"consumed record fell through to older planner");
            // Same request may create, move and rename through separate native commits.
            String q="새 보관함을 만들고 c 파일 옮긴 다음 이름을 c-new.pdf로 바꿔줘";start(host,"multi",q,"create","move","rename");String rev=revision(host);
            JsonObject create=json("{\"parentId\":\"\",\"name\":\"새 보관함\"}");create.addProperty("expectedRevision",rev);JsonObject created=ok(call(host,"library.createFolder",create,q));String dest=created.getAsJsonArray("createdFolders").get(0).getAsJsonObject().get("id").getAsString();
            JsonObject move=ids(revision(host),"document",c);move.addProperty("destinationId",dest);ok(call(host,"library.proposeMove",move,q));
            JsonObject rename=new JsonObject();rename.addProperty("expectedRevision",revision(host));JsonArray renamed=new JsonArray();renamed.add(json("{\"kind\":\"document\",\"id\":\""+c+"\",\"name\":\"c-new.pdf\"}"));rename.add("changes",renamed);ok(call(host,"library.rename",rename,q));
            host.begin("s","undo-multi","방금 파일 작업 되돌려줘");verify(context(host).get("recoveryInterpretationEligible").getAsBoolean(),"file wording blocked recovery interpretation");JsonObject recovery=json("{\"intent\":\"undo\",\"clear\":true,\"evidence\":\"방금 파일 작업 되돌려줘\",\"question\":\"방금 파일 작업 되돌려줘\"}");recovery.add("id",undoArgs(host).get("id"));ok(call(host,"internal.recoveryIntent",recovery,""));JsonObject undone=ok(call(host,"actions.undo",undoArgs(host),"방금 파일 작업 되돌려줘"));
            org=PdfLibraryOrganization.load(root);verify(org.folder(dest)==null&&org.location(c).isEmpty()&&PdfLibraryStore.list(root).stream().anyMatch(item->item.id().equals(c)&&item.name().equals("c.pdf")),"multi-step activity only partly reverted");verify(undone.getAsJsonArray("renamed").get(0).getAsJsonObject().get("name").getAsString().equals("c.pdf"),"UI rename restoration receipt incorrect");
            // A manual edit or import invalidates the whole latest action, without falling back.
            trash(host,"conflict","c 삭제해줘","document",c);JsonObject conflict=undoArgs(host);PdfLibraryOrganization.load(root).createFolder("","직접 편집");host.begin("s","undo-conflict","되돌려줘");denied(call(host,"actions.undo",conflict,"되돌려줘"));verify(context(host).getAsJsonObject("undo").get("domain").getAsString().equals("library")&&PdfLibraryOrganization.load(root).isDocumentInTrash(c),"conflict fell back or changed data");
            // Reads and browsing do not replace the latest mutation, but unrelated sessions cannot inherit it.
            trash(host,"trash-a","a 파일 삭제해줘","document",a);host.begin("different","cross-session","되돌려줘");denied(call(host,"actions.undo",undoArgs(host),"되돌려줘"));host.begin("s","read","파일 목록 보여줘");revision(host);verify(context(host).getAsJsonObject("undo").get("domain").getAsString().equals("library"),"read changed latest action");
            // The truly later planner action wins; undoing it must not expose the older file undo.
            AssistantRecoveryIntentTest.seed(host,"new-planner");verify(context(host).getAsJsonObject("undo").get("domain").getAsString().equals("planner"),"later planner did not replace file record");host.begin("s","undo-plan","되돌려줘");ok(call(host,"actions.undo",undoArgs(host),"되돌려줘"));verify(!context(host).getAsJsonObject("undo").get("available").getAsBoolean()&&context(host).getAsJsonObject("undo").get("domain").getAsString().equals("planner"),"planner undo exposed older file action");
            String remember="앞으로 반말로 해줘";host.begin("s","memory",remember);authorize(host,remember,"memory");ok(call(host,"memory.update",json("{\"expectedRevision\":0,\"set\":{\"tone\":\"casual\"},\"remove\":[]}"),remember));verify(context(host).getAsJsonObject("undo").get("domain").getAsString().equals("memory"),"later memory did not replace earlier domains");
            // Pre-feature file history is a barrier, never permission to undo a different old planner.
            Path state=root.resolve("library-organization.json");JsonObject legacy=json(Files.readString(state));legacy.remove("assistantUndo");Files.writeString(state,legacy.toString());Files.setLastModifiedTime(state,FileTime.fromMillis(context(host).getAsJsonObject("undo").get("at").getAsLong()+100));
            host.begin("s","legacy","다시 되돌려줘");JsonObject legacyInfo=context(host).getAsJsonObject("undo");verify(legacyInfo.get("domain").getAsString().equals("library")&&!legacyInfo.get("available").getAsBoolean()&&!legacyInfo.has("context"),"legacy file activity exposed older record");
            System.out.println("AssistantLibraryUndoTest passed: "+count+" unified-domain, exact restore, grouped action, replay, restart, conflict, session and legacy checks");
        }finally{try(var paths=Files.walk(base)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
