package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Real native transactions on disposable PDFs/notes. No live library or network. */
public final class AssistantRenameTest {
    static int checks,turn;
    static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    static JsonObject obj(String...pairs){JsonObject o=new JsonObject();for(int i=0;i<pairs.length;i+=2)o.addProperty(pairs[i],pairs[i+1]);return o;}
    static JsonObject ref(String kind,String id,String name){return obj("kind",kind,"id",id,"name",name);}
    static JsonObject args(String revision,JsonObject...refs){JsonObject out=obj("expectedRevision",revision);JsonArray list=new JsonArray();for(var r:refs)list.add(r);out.add("changes",list);return out;}
    static JsonObject intent(String q,String scope,String token){JsonObject i=obj("question",q,"decision","request","evidence",q,"sourceScope",scope,"proposalId","","clarificationId",token);i.addProperty("selectionAll",false);JsonArray ops=new JsonArray();ops.add("rename");i.add("operations",ops);return i;}
    static class Ui implements AssistantLibraryUi {
        String current="";int writes,cancelled;
        public JsonObject viewContext(){JsonObject o=obj("screen","library","currentFolderId",current,"search","");o.addProperty("libraryVisible",true);return o;}
        public CompletionStage<JsonObject> navigateFolder(String id){return CompletableFuture.completedFuture(new JsonObject());}
        public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(new JsonObject());}
        public Object prepareMutation(JsonArray c){return c;}
        public void cancelMutation(Object p){cancelled++;}
        public CompletionStage<JsonObject> finishMutation(Object p,JsonObject r){writes++;return CompletableFuture.completedFuture(r);}
    }
    interface Operation{void run()throws Exception;}
    static void denied(Operation op)throws Exception{try{op.run();throw new AssertionError("operation should fail");}catch(IllegalArgumentException expected){checks++;}}
    static String begin(AssistantLibraryActions a,String scope,String q)throws Exception{a.begin("test","turn-"+(++turn),q);a.interpretIntent(intent(q,scope,""));return a.handle("library.query",new JsonObject(),"").get("revision").getAsString();}
    static String rev(AssistantLibraryActions a)throws Exception{return a.handle("library.query",new JsonObject(),"").get("revision").getAsString();}
    static void document(Path root,String id,String name)throws Exception{Path p=root.resolve(id);Files.createDirectories(p.resolve("notes"));Files.writeString(p.resolve("source.pdf"),"%PDF-1.4\nunchanged fixture");Files.writeString(p.resolve("notes/note.txt"),"user note");Properties props=new Properties();props.setProperty("name",name);try(var s=Files.newOutputStream(p.resolve("library.properties"))){props.store(s,"fixture");}}
    static String name(AssistantLibrary library,String kind,String id)throws Exception{return AssistantLibrary.find(library.snapshot(),kind,id).get("name").getAsString();}
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-rename-");
        try{
            var org=PdfLibraryOrganization.load(root);var a=org.createFolder("","수학");var b=org.createFolder("","영어");var sub=org.createFolder(a.id(),"강의");
            String d1="a".repeat(64),d2="b".repeat(64);document(root,d1,"자료1.pdf");document(root,d2,"자료2.pdf");
            AssistantLibrary library=new AssistantLibrary(root);Ui ui=new Ui();AssistantLibraryActions host=new AssistantLibraryActions(library,ui);
            host.begin("test","unauthorized","이름이 뭐야?");String r=rev(host);String initial=r;
            denied(()->host.handle("library.rename",args(initial,ref("folder",a.id(),"가짜")),""));
            host.begin("test","clarify-name","파일 이름 바꿔줘");JsonObject clarification=intent("파일 이름 바꿔줘","all","");clarification.addProperty("decision","clarify");host.interpretIntent(clarification);
            check(host.scopes().isEmpty(),"clarify rename never grants write authority");String clarifyRev=rev(host);
            denied(()->host.handle("library.rename",args(clarifyRev,ref("folder",a.id(),"임의 이름")),host.grant()));
            r=begin(host,"all","수학 폴더 이름을 미적분으로 바꿔줘");JsonObject one=args(r,ref("folder",a.id(),"미적분"));
            JsonObject result=host.handle("library.rename",one,host.grant());check(result.get("renamedCount").getAsInt()==1,"single folder result");
            check(name(library,"folder",a.id()).equals("미적분"),"folder renamed on disk");
            int writes=ui.writes;host.handle("library.rename",one,host.grant());check(ui.writes==writes,"same turn replay does not write twice");
            String receipt=JsonParser.parseString(Files.readString(root.resolve("library-organization.json"))).getAsJsonObject().getAsJsonObject("assistantOperations").keySet().iterator().next();
            JsonObject change=ref("folder",a.id(),"미적분");change.addProperty("operation","rename");JsonArray replayChanges=new JsonArray();replayChanges.add(change);
            JsonObject durable=library.apply(receipt,initial,replayChanges);
            check(durable.get("replayed").getAsBoolean(),"durable receipt wins over stale revision");
            String consentRev=begin(host,"all","그 이름이 딱이네요. 그쪽으로 가는 걸로 하죠.");
            host.handle("library.rename",args(consentRev,ref("folder",a.id(),"미적분 복습")),host.grant());
            check(name(library,"folder",a.id()).equals("미적분 복습"),"AI-interpreted consent needs no approval keyword or template");
            String restoreRev=begin(host,"all","처음 이름이 더 낫겠네요. 처음대로 해두죠.");
            host.handle("library.rename",args(restoreRev,ref("folder",a.id(),"미적분")),host.grant());
            check(name(library,"folder",a.id()).equals("미적분"),"contextual instruction executes without a rename verb whitelist");
            r=begin(host,"all","파일과 폴더 이름을 모두 바꿔줘");
            result=host.handle("library.rename",args(r,ref("document",d1,"수학 1주차.pdf"),ref("document",d2,"영어 단어.pdf"),ref("folder",b.id(),"어휘"),ref("folder",sub.id(),"복습")),host.grant());
            check(result.get("renamedCount").getAsInt()==4,"mixed batch count");
            check(name(library,"document",d1).equals("수학 1주차.pdf")&&PdfLibraryOrganization.load(root).folder(sub.id()).parentId().equals(a.id()),"mixed names and parents persisted");
            check(Files.readString(root.resolve(d1).resolve("source.pdf")).endsWith("unchanged fixture")&&Files.readString(root.resolve(d1).resolve("notes/note.txt")).equals("user note"),"PDF and notes preserved");
            // Final-state validation permits swaps for both entity kinds.
            r=begin(host,"all","폴더 두 개와 파일 두 개 이름을 서로 바꿔줘");
            host.handle("library.rename",args(r,ref("folder",a.id(),"어휘"),ref("folder",b.id(),"미적분"),ref("document",d1,"영어 단어.pdf"),ref("document",d2,"수학 1주차.pdf")),host.grant());
            check(name(library,"folder",a.id()).equals("어휘")&&name(library,"document",d1).equals("영어 단어.pdf"),"folder/document swaps are atomic");
            r=begin(host,"all","두 파일 이름 바꿔줘");String unchanged=library.snapshot().toString();String collisionRev=r;
            denied(()->host.handle("library.rename",args(collisionRev,ref("folder",sub.id(),"변경되면안됨"),ref("document",d1,"수학 1주차.pdf")),host.grant()));
            check(library.snapshot().toString().equals(unchanged),"one collision rolls back entire mixed batch");
            for(String invalid:List.of("", "../경로", "경로\\파일", ".", "..", "a\nb", "가".repeat(201))){
                String badRev=begin(host,"all","파일 이름 변경해줘");String before=library.snapshot().toString();
                denied(()->host.handle("library.rename",args(badRev,ref("document",d1,invalid)),host.grant()));
                check(library.snapshot().toString().equals(before),"invalid name did not mutate: "+invalid.length());
            }
            String dupRev=begin(host,"all","이름 바꿔줘");denied(()->host.handle("library.rename",args(dupRev,ref("document",d1,"하나.pdf"),ref("document",d1,"둘.pdf")),host.grant()));
            String stale=begin(host,"all","파일 이름 바꿔줘");PdfLibraryStore.rename(root,d1,"수동 변경.pdf");
            denied(()->host.handle("library.rename",args(stale,ref("document",d1,"오래된 요청.pdf")),host.grant()));
            check(name(library,"document",d1).equals("수동 변경.pdf"),"manual UI rename supersedes old query and canonical name");
            ui.current=a.id();String scoped=begin(host,"current","이 폴더 안의 파일 이름만 바꿔줘");
            denied(()->host.handle("library.rename",args(scoped,ref("document",d1,"범위 밖.pdf")),host.grant()));ui.current="";
            // Ambiguous source: candidate selection cannot change the requested destination name.
            var latest=PdfLibraryOrganization.load(root);var dup1=latest.createFolder(a.id(),"공통");var dup2=latest.createFolder(b.id(),"공통");
            String amb=begin(host,"all","공통 폴더 이름을 공통 복습으로 바꿔줘");denied(()->host.handle("library.rename",args(amb,ref("folder",dup1.id(),"공통 복습")),host.grant()));
            String token=host.context().getAsJsonObject("pendingClarification").get("clarificationId").getAsString();
            host.begin("test","choice","두번째");host.interpretIntent(intent("두번째","all",token));String choiceRev=rev(host);
            denied(()->host.handle("library.rename",args(choiceRev,ref("folder",dup2.id(),"다른 이름")),host.grant()));
            host.handle("library.rename",args(choiceRev,ref("folder",dup2.id(),"공통 복습")),host.grant());check(name(library,"folder",dup1.id()).equals("공통")&&name(library,"folder",dup2.id()).equals("공통 복습"),"duplicate choice bound to original name and candidates");
            String noop=begin(host,"all","수동 변경.pdf 이름은 수동 변경.pdf로 해줘");result=host.handle("library.rename",args(noop,ref("document",d1,"수동 변경.pdf")),host.grant());check(result.get("renamedCount").getAsInt()==0&&result.get("unchangedCount").getAsInt()==1,"no-op reported accurately");
            JsonArray over=new JsonArray();for(int i=0;i<101;i++)over.add(ref("document",d1,"새 이름"+i));JsonObject tooMany=obj("expectedRevision",begin(host,"all","전부 바꿔줘"));tooMany.add("changes",over);denied(()->host.handle("library.rename",tooMany,host.grant()));
            JsonArray bulk=new JsonArray();var bulkOrg=PdfLibraryOrganization.load(root);
            for(int i=0;i<100;i++){var folder=bulkOrg.createFolder("","일괄 원본 "+i);bulk.add(ref("folder",folder.id(),"일괄 변경 "+i));}
            begin(host,"root","일괄 원본 폴더 100개 이름을 바꿔줘");int offset=0;String pageRev="";
            while(true){JsonObject query=new JsonObject();query.addProperty("limit",100);query.addProperty("offset",offset);if(offset>0)query.addProperty("expectedRevision",pageRev);
                JsonObject page=host.handle("library.query",query,"");pageRev=page.get("revision").getAsString();if(!page.get("hasMore").getAsBoolean())break;offset=page.get("nextOffset").getAsInt();}
            JsonObject batch=obj("expectedRevision",pageRev);batch.add("changes",bulk);result=host.handle("library.rename",batch,host.grant());
            check(result.get("renamedCount").getAsInt()==100,"100-item batch after pagination");
            for(JsonElement item:bulk){JsonObject ref=item.getAsJsonObject();check(name(library,"folder",ref.get("id").getAsString()).equals(ref.get("name").getAsString()),"bulk item persisted");}
            PdfLibraryOrganization.load(root).forgetDocument(d1);
            check(name(library,"document",d1).equals("자료1.pdf"),"removing a root document also clears its renamed alias for future imports");
            System.out.println("AssistantRenameTest OK · "+checks+" checks · mixed batch, swap, rollback, duplicate choice, replay, scope, stale, PDF/notes preservation");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
