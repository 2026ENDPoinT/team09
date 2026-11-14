package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Disposable virtual libraries only; no user files, network, windows or paid calls. */
public final class AssistantSourceFolderTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    interface Operation{void run()throws Exception;}
    static void denied(String code,Operation operation)throws Exception{
        try{operation.run();throw new AssertionError("expected "+code);}
        catch(AssistantLibraryActions.Denied failure){check(failure.code.equals(code),failure.code+": "+failure.getMessage());}
    }
    static JsonObject obj(String... values){JsonObject o=new JsonObject();for(int i=0;i<values.length;i+=2)o.addProperty(values[i],values[i+1]);return o;}
    static final class Ui implements AssistantLibraryUi {
        String folder="";int writes;Runnable beforeSave=()->{},afterSave=()->{};
        public JsonObject viewContext(){return obj("currentFolderId",folder,"screen","library","section","documents","search","");}
        public CompletionStage<JsonObject> navigateFolder(String id){folder=id;return CompletableFuture.completedFuture(obj("status","opened"));}
        public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(obj("status","opened"));}
        public Object prepareMutation(JsonArray changes){beforeSave.run();return changes;}
        public void cancelMutation(Object prepared){}
        public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){writes++;afterSave.run();return CompletableFuture.completedFuture(result);}
    }
    static final class Fixture implements AutoCloseable {
        final Path root=Files.createTempDirectory("assistant-source-folder-");
        final AssistantLibrary library=new AssistantLibrary(root);final Ui ui=new Ui();
        final AssistantLibraryActions host=new AssistantLibraryActions(library,ui);
        final String source,destination,other;
        final List<String> inside=new ArrayList<>();final String outside="f".repeat(64);
        Fixture(int count,boolean duplicateInside)throws Exception{
            var org=PdfLibraryOrganization.load(root);source=org.createFolder("","의미없는것들").id();destination=org.createFolder("","보관함").id();other=org.createFolder("","다른폴더").id();
            for(int i=0;i<count;i++){
                String id=String.format("%064x",i+1);inside.add(id);
                document(id,i==0||duplicateInside&&i==1?"document (3).pdf":"자료 "+i+".pdf");org.moveDocument(id,source);
            }
            document(outside,"document (3).pdf");
        }
        void document(String id,String name)throws Exception{
            Path folder=root.resolve(id);Files.createDirectories(folder.resolve("notes"));Files.writeString(folder.resolve("source.pdf"),"%PDF fixture unchanged "+id);
            Files.writeString(folder.resolve("notes/note.txt"),"preserved");Properties properties=new Properties();properties.setProperty("name",name);
            try(var stream=Files.newOutputStream(folder.resolve("library.properties"))){properties.store(stream,"fixture");}
        }
        JsonObject intent(String question,String decision,String folder,String operation,boolean all){
            JsonObject i=obj("question",question,"decision",decision,"evidence",question,"sourceScope","all","proposalId","","clarificationId","");
            i.addProperty("sourceFolderId",folder);i.addProperty("selectionAll",all);JsonArray ops=new JsonArray();ops.add(operation);i.add("operations",ops);return i;
        }
        void begin(String operation,boolean all)throws Exception{
            String q="의미없는것들 폴더 안의 항목을 "+operation+" 해줘";
            host.begin("session",UUID.randomUUID().toString(),q);host.interpretIntent(intent(q,"request",source,operation,all));
        }
        String query(boolean global)throws Exception{
            JsonObject args=new JsonObject();if(!global)args.addProperty("parentId",source);args.addProperty("limit",100);
            return host.handle("library.query",args,"").get("revision").getAsString();
        }
        JsonObject ids(String revision,List<String> ids){JsonObject a=obj("expectedRevision",revision);JsonArray refs=new JsonArray();ids.forEach(id->refs.add(obj("kind","document","id",id)));a.add("ids",refs);return a;}
        String location(String id)throws Exception{return PdfLibraryOrganization.load(root).location(id);}
        public void close()throws Exception{try(var files=Files.walk(root)){for(Path p:files.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}}
    }
    public static void main(String[]args)throws Exception{
        // Exact shape of the reported incident: 13 children, same-name file outside.
        try(Fixture f=new Fixture(13,false)){
            f.begin("trash",true);String revision=f.query(false);f.ui.folder=f.other;
            JsonObject r=f.host.handle("library.trash",f.ids(revision,f.inside),f.host.grant());
            check(r.get("trashedCount").getAsInt()==13,"13-item folder request did not execute");
            for(String id:f.inside){check(f.location(id).equals(PdfLibraryOrganization.TRASH_ID),"inside item not trashed");check(Files.readString(f.root.resolve(id).resolve("notes/note.txt")).equals("preserved"),"notes changed");}
            check(f.location(f.outside).isEmpty(),"outside duplicate was touched");check(f.ui.writes==1,"whole folder not atomic");
        }
        try(Fixture f=new Fixture(3,true)){
            f.begin("trash",true);String revision=f.query(false);
            f.host.handle("library.trash",f.ids(revision,f.inside),f.host.grant());
            check(f.location(f.outside).isEmpty(),"same-name whole selection included outside item");
            check(f.location(f.inside.get(1)).equals(PdfLibraryOrganization.TRASH_ID),"in-scope duplicate was rejected");
        }
        try(Fixture f=new Fixture(2,false)){
            f.begin("trash",true);String revision=f.query(true);String before=f.library.snapshot().toString();
            denied("library_scope_changed",()->f.host.handle("library.trash",f.ids(revision,List.of(f.inside.get(0),f.outside)),f.host.grant()));
            check(before.equals(f.library.snapshot().toString())&&f.ui.writes==0,"scope error partially committed");
        }
        try(Fixture f=new Fixture(2,true)){
            f.begin("trash",false);String revision=f.query(false);
            denied("library_ambiguous",()->f.host.handle("library.trash",f.ids(revision,List.of(f.inside.get(0))),f.host.grant()));
            JsonObject pending=f.host.context().getAsJsonObject("pendingClarification");
            check(pending.getAsJsonArray("candidates").size()==2,"outside duplicates leaked into scoped question");
            check(pending.get("sourceFolderId").getAsString().equals(f.source),"scope lost from clarification");
            String q="두번째 항목으로 해줘";f.host.begin("session","choice",q);
            JsonObject intent=f.intent(q,"request",null,"trash",false);intent.add("clarificationId",pending.get("clarificationId"));f.host.interpretIntent(intent);
            String latest=f.query(true);
            f.host.handle("library.trash",f.ids(latest,List.of(f.inside.get(1))),f.host.grant());
            check(f.location(f.inside.get(0)).equals(f.source)&&f.location(f.outside).isEmpty(),"candidate selection expanded source");
        }
        try(Fixture f=new Fixture(2,false)){
            f.begin("move",true);String revision=f.query(false);
            // Destination must still be observed independently, outside the source bound.
            f.query(true);JsonObject command=f.ids(revision,f.inside);command.addProperty("destinationId",f.destination);
            f.host.handle("library.proposeMove",command,f.host.grant());
            check(f.location(f.inside.get(0)).equals(f.destination)&&f.location(f.outside).isEmpty(),"move did not preserve source/destination separation");
        }
        try(Fixture f=new Fixture(2,false)){
            f.begin("rename",false);String revision=f.query(false);JsonObject command=obj("expectedRevision",revision);JsonArray changes=new JsonArray();changes.add(obj("kind","document","id",f.inside.get(0),"name","새 표시 이름.pdf"));command.add("changes",changes);
            f.host.handle("library.rename",command,f.host.grant());
            check(AssistantLibrary.find(f.library.snapshot(),"document",f.inside.get(0)).get("name").getAsString().equals("새 표시 이름.pdf"),"scoped rename blocked by outside name");
            check(Files.readString(f.root.resolve(f.inside.get(0)).resolve("source.pdf")).endsWith(f.inside.get(0)),"physical file changed");
        }
        try(Fixture f=new Fixture(2,false)){
            var org=PdfLibraryOrganization.load(f.root);org.createFolder(f.other,"의미없는것들");f.begin("trash",true);String revision=f.query(false);
            denied("library_ambiguous",()->f.host.handle("library.trash",f.ids(revision,f.inside),f.host.grant()));
            check(f.ui.writes==0,"ambiguous source folder was auto-selected");
        }
        try(Fixture f=new Fixture(2,false)){
            f.begin("trash",true);String revision=f.query(false);PdfLibraryStore.rename(f.root,f.inside.get(0),"수동 변경.pdf");
            denied("library_stale",()->f.host.handle("library.trash",f.ids(revision,f.inside),f.host.grant()));
            check(f.ui.writes==0,"stale source selection mutated files");
        }
        System.out.println("AssistantSourceFolderTest OK: "+checks+" checks; 13-item replay, duplicates, scope, atomicity, choices, navigation, move, rename, stale revision");
    }
}
