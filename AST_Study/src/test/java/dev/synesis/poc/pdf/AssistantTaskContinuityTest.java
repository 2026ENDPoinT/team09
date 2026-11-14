package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Disposable native transactions only: task identity survives navigation, not data conflicts. */
public final class AssistantTaskContinuityTest {
    private static int checks,turn;
    private static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
    private static JsonObject obj(String... pairs){JsonObject out=new JsonObject();for(int i=0;i<pairs.length;i+=2)out.addProperty(pairs[i],pairs[i+1]);return out;}
    private static JsonObject intent(String question,String decision,String source,String token,boolean all,String... operations){
        JsonObject out=obj("question",question,"decision",decision,"evidence",question,"sourceScope",source,"proposalId","","clarificationId",token);
        out.addProperty("selectionAll",all);JsonArray ops=new JsonArray();for(String operation:operations)ops.add(operation);out.add("operations",ops);return out;
    }
    private static void begin(AssistantLibraryActions host,String question)throws Exception{host.begin("chat","turn-"+(++turn),question);}
    private static String revision(AssistantLibraryActions host)throws Exception{return host.handle("library.query",new JsonObject(),"").get("revision").getAsString();}
    private static JsonObject rename(String revision,String... idNames){JsonObject out=obj("expectedRevision",revision);JsonArray changes=new JsonArray();for(int i=0;i<idNames.length;i+=2)changes.add(obj("kind","document","id",idNames[i],"name",idNames[i+1]));out.add("changes",changes);return out;}
    private static JsonObject move(String revision,String id,String destination){JsonObject out=obj("expectedRevision",revision,"destinationId",destination);JsonArray ids=new JsonArray();ids.add(obj("kind","document","id",id));out.add("ids",ids);return out;}
    private static String name(AssistantLibrary library,String id)throws Exception{return AssistantLibrary.find(library.snapshot(),"document",id).get("name").getAsString();}
    private static void document(Path root,String id,String name)throws Exception{
        Path folder=root.resolve(id);Files.createDirectories(folder.resolve("notes"));Files.writeString(folder.resolve("source.pdf"),"%PDF-1.4 unchanged source");Files.writeString(folder.resolve("notes/note.txt"),"unchanged note");
        Properties properties=new Properties();properties.setProperty("name",name);try(var output=Files.newOutputStream(folder.resolve("library.properties"))){properties.store(output,"fixture");}
    }
    private interface Work{void run()throws Exception;}
    private static void denied(String code,Work work)throws Exception{try{work.run();throw new AssertionError("expected "+code);}catch(AssistantLibraryActions.Denied failure){check(code.equals(failure.code),failure.code+": "+failure.getMessage());}}
    private static final class Ui implements AssistantLibraryUi {
        String folder="",screen="library",search="";int writes;
        public JsonObject viewContext(){JsonObject out=obj("currentFolderId",folder,"currentPath",folder,"screen",screen,"section",screen,"search",search);out.addProperty("libraryVisible",screen.equals("library"));return out;}
        public CompletionStage<JsonObject> navigateFolder(String id){folder=id;return CompletableFuture.completedFuture(obj("status","opened"));}
        public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(obj("status","opened"));}
        public Object prepareMutation(JsonArray changes){return changes;}
        public void cancelMutation(Object prepared){}
        public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){writes++;return CompletableFuture.completedFuture(result);}
    }
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-task-continuity-");
        try{
            var organization=PdfLibraryOrganization.load(root);var course=organization.createFolder("","오늘의한국사회");var elsewhere=organization.createFolder("","다른자료");
            String first="a".repeat(64),second="b".repeat(64),other="c".repeat(64),rootDoc="d".repeat(64);
            document(root,first,"2주차_OECD 통계.pdf");document(root,second,"2주차_한국사회를 보는 시각.pdf");document(root,other,"다른자료.pdf");document(root,rootDoc,"루트자료.pdf");
            organization.moveDocument(first,course.id());organization.moveDocument(second,course.id());organization.moveDocument(other,elsewhere.id());
            Ui ui=new Ui();AssistantLibrary library=new AssistantLibrary(root);AssistantLibraryActions host=new AssistantLibraryActions(library,ui);

            String direct="여기 파일 이름을 정리해줘";begin(host,direct);host.interpretIntent(intent(direct,"request","current","",false,"rename"));String initial=revision(host);
            ui.folder=elsewhere.id();ui.screen="planner";ui.search="다른 검색";
            denied("library_scope_changed",()->host.handle("library.rename",rename(initial,other,"잘못된 대상.pdf"),host.grant()));
            host.handle("library.rename",rename(initial,rootDoc,"정리한 루트자료.pdf"),host.grant());
            check(name(library,rootDoc).equals("정리한 루트자료.pdf")&&name(library,other).equals("다른자료.pdf"),"navigation/search changes neither cancel nor retarget a request");

            // The remembered library folder remains addressable while viewing a PDF/planner.
            ui.folder=elsewhere.id();ui.screen="other";begin(host,"이 폴더 파일 이름 바꿔줘");host.interpretIntent(intent("이 폴더 파일 이름 바꿔줘","request","current","",false,"rename"));
            host.handle("library.rename",rename(revision(host),other,"다른자료 정리.pdf"),host.grant());check(name(library,other).equals("다른자료 정리.pdf"),"hidden library supports explicit work without a visibility gate");

            // Replay the screenshot: naming collision question, unrelated screen, brief human choice.
            ui.folder=course.id();ui.screen="library";ui.search="";String request="이 폴더 파일들을 n주차로 모두 바꿔줘";begin(host,request);revision(host);
            host.interpretIntent(intent(request,"clarify","current","",true,"rename"));check(host.scopes().isEmpty(),"clarification stores context without granting writes");
            JsonObject pending=host.context().getAsJsonObject("pendingRequest");String token=pending.get("clarificationId").getAsString();
            String confirmation="동명 파일이 생기니 주차 뒤에 구분 이름을 남길까요?";
            host.finish(confirmation);
            int writesBeforeDiscussion=ui.writes;
            begin(host,"구분 이름을 남긴다는 게 무슨 뜻이야?");
            host.interpretIntent(intent("구분 이름을 남긴다는 게 무슨 뜻이야?","none","all",token,false));
            host.finish("주차 뒤에 원래 제목을 남겨 두 파일을 구별한다는 뜻이에요.");
            for(int i=0;i<24;i++){
                begin(host,"다른 이야기 "+i);host.interpretIntent(intent("다른 이야기 "+i,"none","all","",false));host.finish("일반 대화 답변");
            }
            JsonObject retained=host.context().getAsJsonObject("pendingRequest");
            check(retained.get("confirmationQuestion").getAsString().equals(confirmation)&&retained.getAsJsonArray("discussion").size()==1,"confirmation and related explanation survive unrelated conversation");
            check(ui.writes==writesBeforeDiscussion&&host.scopes().isEmpty(),"explanation and unrelated chat never grant writes");
            check(pending.get("request").getAsString().equals(request)&&pending.getAsJsonObject("requestView").get("currentFolderId").getAsString().equals(course.id())&&pending.getAsJsonArray("targets").size()>=2,"original request, source folder and actual target references are retained");
            ui.folder=elsewhere.id();ui.screen="planner";ui.search="검색 변경";begin(host,"오늘 일정도 보여줘");host.interpretIntent(intent("오늘 일정도 보여줘","none","all","",false));
            check(host.context().getAsJsonObject("pendingRequest").get("clarificationId").getAsString().equals(token),"read-only intermediate conversation does not erase unfinished task");
            begin(host,"확장자는 남기고 해줘");host.interpretIntent(intent("확장자는 남기고 해줘","clarify","all",token,true,"rename"));
            JsonObject more=host.context().getAsJsonObject("pendingRequest");
            check(host.scopes().isEmpty()&&more.get("clarificationId").getAsString().equals(token)&&more.get("request").getAsString().contains("확장자는 남기고 해줘")&&more.getAsJsonObject("requestView").get("currentFolderId").getAsString().equals(course.id()),"another clarification preserves the token, original folder and intervening human condition");
            begin(host,"일부 남겨서 구분해줘");
            denied("library_permission_required",()->host.interpretIntent(intent("일부 남겨서 구분해줘","request","all",token,true,"trash")));
            host.interpretIntent(intent("일부 남겨서 구분해줘","request","all",token,true,"rename"));
            check(host.context().getAsJsonObject("requestView").get("currentFolderId").getAsString().equals(course.id()),"follow-up uses original source even when model sends live all scope");
            String follow=revision(host);denied("library_scope_changed",()->host.handle("library.rename",rename(follow,other,"범위밖.pdf"),host.grant()));
            host.handle("library.rename",rename(follow,first,"2주차_OECD.pdf",second,"2주차_한국사회.pdf"),host.grant());
            check(name(library,first).equals("2주차_OECD.pdf")&&name(library,second).equals("2주차_한국사회.pdf")&&!host.context().has("pendingRequest"),"brief choice completes exactly the original files and clears pending context");
            check(Files.readString(root.resolve(first).resolve("source.pdf")).equals("%PDF-1.4 unchanged source")&&Files.readString(root.resolve(first).resolve("notes/note.txt")).equals("unchanged note"),"source and generated/user data are untouched by naming");
            begin(host,"그대로 해줘");denied("library_permission_required",()->host.interpretIntent(intent("그대로 해줘","request","all",token,true,"rename")));

            ui.folder=course.id();String moveQuestion="이 파일을 저쪽 폴더로 옮길까?";begin(host,moveQuestion);host.interpretIntent(intent(moveQuestion,"clarify","current","",false,"move"));
            String proposal;
            try{host.handle("library.proposeMove",move(revision(host),first,elsewhere.id()),host.grant());throw new AssertionError("expected confirmation");}
            catch(AssistantLibraryActions.Denied failure){check(failure.code.equals("confirmation_required"),"immutable move proposal prepared");proposal=failure.proposalId;}
            ui.screen="profile";ui.folder="";begin(host,"응 그대로 해줘");JsonObject approval=intent("응 그대로 해줘","approve","all","",false,"move");approval.addProperty("proposalId",proposal);host.interpretIntent(approval);
            host.handle("library.confirmMove",obj("proposalId",proposal),host.grant());check(PdfLibraryOrganization.load(root).location(first).equals(elsewhere.id()),"fixed move approval survives screen and folder changes");

            begin(host,"이름을 바꾸자");host.interpretIntent(intent("이름을 바꾸자","request","all","",false,"rename"));String stale=revision(host);PdfLibraryStore.rename(root,second,"수동 편집.pdf");
            denied("library_stale",()->host.handle("library.rename",rename(stale,second,"덮어쓰면안됨.pdf"),host.grant()));check(name(library,second).equals("수동 편집.pdf"),"actual intervening data edits still require fresh verification");

            begin(host,"이 파일 이름 바꿔줘");host.interpretIntent(intent("이 파일 이름 바꿔줘","clarify","all","",false,"rename"));String cancelToken=host.context().getAsJsonObject("pendingRequest").get("clarificationId").getAsString();
            begin(host,"그 작업 취소해");host.interpretIntent(intent("그 작업 취소해","reject","all","",false));check(!host.context().has("pendingRequest"),"explicit human cancellation clears unfinished task");
            begin(host,"그 이름으로 해줘");denied("library_permission_required",()->host.interpretIntent(intent("그 이름으로 해줘","request","all",cancelToken,false,"rename")));
            begin(host,"파일 이름 정해줘");host.interpretIntent(intent("파일 이름 정해줘","clarify","all","",false,"rename"));String cross=host.context().getAsJsonObject("pendingRequest").get("clarificationId").getAsString();
            host.begin("other-chat","new-chat","그 이름으로 해줘");denied("library_permission_required",()->host.interpretIntent(intent("그 이름으로 해줘","request","all",cross,false,"rename")));
            System.out.println("AssistantTaskContinuityTest OK · "+checks+" checks");
        }finally{try(var files=Files.walk(root)){for(Path path:files.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}
