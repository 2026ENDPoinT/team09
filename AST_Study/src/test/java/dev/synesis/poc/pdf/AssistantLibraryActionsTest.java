package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

/** Source-only host replay with a fake UI and disposable library; no windows, network or live data. */
public final class AssistantLibraryActionsTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static JsonObject json(String text){return JsonParser.parseString(text).getAsJsonObject();}
    private static JsonObject query(AssistantLibraryActions actions)throws Exception{return actions.handle("library.query",new JsonObject(),"");}
    private static JsonObject args(String kind,String id,String revision){JsonObject result=new JsonObject();result.addProperty("kind",kind);result.addProperty("id",id);result.addProperty("expectedRevision",revision);return result;}
    private static String revision(AssistantLibraryActions actions)throws Exception{return query(actions).get("revision").getAsString();}
    private static AssistantLibraryActions.Denied denied(String code,Throwing operation)throws Exception{
        try{operation.run();throw new AssertionError("expected denial: "+code);}catch(AssistantLibraryActions.Denied failure){check(failure.code.equals(code),failure.code+": "+failure.getMessage());return failure;}
    }
    private interface Throwing {void run()throws Exception;}
    private static final class FakeUi implements AssistantLibraryUi {
        final Path root;String folder="";int navigationCount,openCount,preparedCount,finishedCount,cancelledCount;
        FakeUi(Path root){this.root=root;}
        public JsonObject viewContext()throws Exception{
            PdfLibraryOrganization organization=PdfLibraryOrganization.load(root);JsonObject context=new JsonObject();
            context.addProperty("screen","library");context.addProperty("libraryVisible",true);context.addProperty("currentFolderId",folder);context.addProperty("currentPath",organization.displayPath(folder));
            context.addProperty("search","");context.addProperty("recentSection",false);
            // Deliberately changes with own commits like the real UI; host scope binds screen/folder, not catalog bytes.
            context.addProperty("viewRevision",folder+":"+organization.revision());JsonArray visible=new JsonArray();
            for(var item:organization.folders())if(item.parentId().equals(folder)){JsonObject row=new JsonObject();row.addProperty("kind","folder");row.addProperty("id",item.id());visible.add(row);}
            context.add("visibleItems",visible);return context;
        }
        public CompletionStage<JsonObject> navigateFolder(String id){boolean same=folder.equals(id);if(!same){navigationCount++;folder=id;}JsonObject result=new JsonObject();result.addProperty("status",same?"already_open":"opened");result.addProperty("id",id);return CompletableFuture.completedFuture(result);}
        public CompletionStage<JsonObject> openDocument(String id){openCount++;JsonObject result=new JsonObject();result.addProperty("status","opened");result.addProperty("id",id);return CompletableFuture.completedFuture(result);}
        public Object prepareMutation(JsonArray changes){preparedCount++;return new Object();}
        public void cancelMutation(Object prepared){cancelledCount++;}
        public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){finishedCount++;return CompletableFuture.completedFuture(result);}
    }
    private static JsonObject intent(String question,String decision,String evidence,String source,String proposal,boolean all,String... operations){
        JsonObject out=new JsonObject();out.addProperty("question",question);out.addProperty("decision",decision);out.addProperty("evidence",evidence);out.addProperty("sourceScope",source);out.addProperty("proposalId",proposal);out.addProperty("clarificationId","");out.addProperty("selectionAll",all);JsonArray ops=new JsonArray();for(String operation:operations)ops.add(operation);out.add("operations",ops);return out;
    }
    private static void request(AssistantLibraryActions actions,String turn,String question,String source,boolean all,String... operations)throws Exception{
        actions.begin("s",turn,question);actions.interpretIntent(intent(question,"request",question,source,"",all,operations));
    }
    private static JsonObject move(String source,String destination,String revision){
        JsonObject out=new JsonObject();out.addProperty("destinationId",destination);out.addProperty("expectedRevision",revision);JsonArray ids=new JsonArray();JsonObject ref=new JsonObject();ref.addProperty("kind","folder");ref.addProperty("id",source);ids.add(ref);out.add("ids",ids);return out;
    }
    private static JsonObject pending(AssistantLibraryActions actions,FakeUi ui,Path root,String destination,String name,String turn)throws Exception{
        ui.folder="";var source=PdfLibraryOrganization.load(root).createFolder("",name);String question="이 자료 폴더를 그쪽 모음 폴더로 정리해 두면 좋겠어";
        actions.begin("s",turn,question);actions.interpretIntent(intent(question,"clarify",question,"root","",false,"move"));
        JsonObject command=move(source.id(),destination,revision(actions));int writes=ui.preparedCount;
        AssistantLibraryActions.Denied proposal=denied("confirmation_required",()->actions.handle("library.proposeMove",command,actions.grant()));
        check(PdfLibraryOrganization.load(root).folder(source.id()).parentId().isEmpty()&&ui.preparedCount==writes,"clarify move only prepares immutable proposal");
        JsonObject result=new JsonObject();result.addProperty("proposalId",proposal.proposalId);result.addProperty("sourceId",source.id());return result;
    }
    private static JsonObject confirm(JsonObject proposal){JsonObject out=new JsonObject();out.add("proposalId",proposal.get("proposalId"));return out;}
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-semantic-library-");var organization=PdfLibraryOrganization.load(root);
        var parent=organization.createFolder("","폴더1");var inner=organization.createFolder(parent.id(),"폴더3");var destination=organization.createFolder("","기출모음");var other=organization.createFolder("","폴더4");
        var duplicateA=organization.createFolder(parent.id(),"2021기출");var duplicateB=organization.createFolder(other.id(),"2021기출");var source=organization.createFolder("","출제자료");
        FakeUi ui=new FakeUi(root);AssistantLibraryActions actions=new AssistantLibraryActions(new AssistantLibrary(root),ui);
        actions.begin("s","no-semantic","폴더1 열어줘");String rev=revision(actions);
        denied("library_permission_required",()->actions.handle("library.open",args("folder",parent.id(),revision(actions)),actions.grant()));check(actions.scopes().isEmpty(),"keywords alone grant no native authority");
        check(actions.context().get("semanticAuthorization").getAsBoolean(),"semantic authorization capability exposed");
        String quotedName="‘폴더1’ 열어줘";actions.begin("s","quoted-name",quotedName);actions.interpretIntent(intent(quotedName,"request",quotedName,"all","",false,"open"));
        actions.handle("library.open",args("folder",parent.id(),revision(actions)),actions.grant());check(ui.folder.equals(parent.id()),"quoted item name preserves the direct unquoted command");

        ui.folder=inner.id();request(actions,"ancestor","앞서 보던 상위 자료함으로 돌아가면 좋겠어","all",false,"open");rev=revision(actions);
        int previousNavigations=ui.navigationCount;JsonObject open=args("folder",parent.id(),rev);actions.handle("library.open",open,actions.grant());actions.handle("library.open",open,actions.grant());check(ui.folder.equals(parent.id())&&ui.navigationCount==previousNavigations+1,"semantic open reuses mouse route once despite retry");
        JsonObject canonical=intent("앞서 보던 상위 자료함으로 돌아가면 좋겠어","request","앞서 보던 상위 자료함으로 돌아가면 좋겠어","all","",false,"open");check(actions.interpretIntent(canonical).get("replayed").getAsBoolean(),"identical semantic judgment is idempotent");
        denied("library_permission_required",()->actions.interpretIntent(intent("앞서 보던 상위 자료함으로 돌아가면 좋겠어","none","","all","",false)));

        ui.folder="";request(actions,"create","여기에 기출을 모아 둘 자리를 마련해 줬으면 해","root",false,"create");rev=revision(actions);JsonObject create=new JsonObject();create.addProperty("parentId","");create.addProperty("name","새모음");create.addProperty("expectedRevision",rev);
        int foldersBefore=PdfLibraryOrganization.load(root).folders().size();actions.handle("library.createFolder",create,actions.grant());actions.handle("library.createFolder",create,actions.grant());check(PdfLibraryOrganization.load(root).folders().size()==foldersBefore+1,"semantic create without lexical allowlist, one commit on retry");
        denied("library_permission_required",()->actions.handle("library.proposeMove",move(source.id(),destination.id(),revision(actions)),actions.grant()));

        request(actions,"direct-move","출제자료는 기출모음으로 정리해 놓는 걸로 하자","root",false,"move");JsonObject direct=move(source.id(),destination.id(),revision(actions));int before=ui.preparedCount;
        JsonObject moved=actions.handle("library.proposeMove",direct,actions.grant());actions.handle("library.proposeMove",direct,actions.grant());check(PdfLibraryOrganization.load(root).folder(source.id()).parentId().equals(destination.id())&&moved.get("movedCount").getAsInt()==1&&ui.preparedCount==before+1,"clear semantic move executes without redundant confirmation or duplicate effect");

        request(actions,"duplicate","2021기출 자료함을 확인하고 싶어","all",false,"open");String dupRev=revision(actions);
        denied("library_ambiguous",()->actions.handle("library.open",args("folder",duplicateA.id(),dupRev),actions.grant()));check(actions.context().has("pendingClarification"),"duplicate choices preserve original request");
        String choiceToken=actions.context().getAsJsonObject("pendingClarification").get("clarificationId").getAsString();
        actions.begin("s","choice-attack","두번째");JsonObject selection=intent("두번째","request","두번째","all","",false,"open");selection.addProperty("clarificationId",choiceToken);actions.interpretIntent(selection);rev=revision(actions);
        denied("library_permission_required",()->actions.handle("library.open",args("folder",destination.id(),revision(actions)),actions.grant()));
        actions.handle("library.open",args("folder",duplicateB.id(),rev),actions.grant());check(ui.folder.equals(duplicateB.id()),"semantic ordinal choice remains bound to original candidate IDs");

        // A new explicit request omits clarificationId and must not inherit an older duplicate choice.
        request(actions,"duplicate-again","2021기출 자료함을 보고 싶어","all",false,"open");String ambiguousAgain=revision(actions);
        denied("library_ambiguous",()->actions.handle("library.open",args("folder",duplicateA.id(),ambiguousAgain),actions.grant()));
        request(actions,"new-open","기출모음 쪽을 확인하고 싶어","all",false,"open");actions.handle("library.open",args("folder",destination.id(),revision(actions)),actions.grant());check(ui.folder.equals(destination.id())&&!actions.context().has("pendingClarification"),"new open request is independent of old same-operation clarification");
        // Native navigation updates expected live view but not the original source binding.
        ui.folder="";var multiSource=PdfLibraryOrganization.load(root).createFolder("","멀티작업자료");
        request(actions,"compound","지금 보이는 자료를 정리할 자리를 폴더1에 마련하고 화면도 그쪽으로 보여줘","current",false,"open","create","move");
        actions.handle("library.open",args("folder",parent.id(),revision(actions)),actions.grant());
        JsonObject make=new JsonObject();make.addProperty("parentId",parent.id());make.addProperty("name","복합정리");make.addProperty("expectedRevision",revision(actions));JsonObject compoundCreated=actions.handle("library.createFolder",make,actions.grant());String compoundDestination=compoundCreated.getAsJsonArray("createdFolders").get(0).getAsJsonObject().get("id").getAsString();
        denied("library_scope_changed",()->actions.handle("library.proposeMove",move(inner.id(),compoundDestination,revision(actions)),actions.grant()));
        actions.handle("library.proposeMove",move(multiSource.id(),compoundDestination,revision(actions)),actions.grant());check(PdfLibraryOrganization.load(root).folder(multiSource.id()).parentId().equals(compoundDestination),"own navigation permits following actions while current-source binding stays at request origin");

        for(String answer:List.of("엉 맞어","ㅇ","어","그래","좋아요 거기로 옮겨줘","허락할게","그 폴더로 이동해 주세요","해줘. 승인할게","그 방향이면 충분하니 실행 부탁해")){
            JsonObject proposal=pending(actions,ui,root,destination.id(),"승인자료"+checks,"approval-proposal-"+checks);JsonObject confirm=confirm(proposal);
            denied("library_permission_required",()->actions.handle("library.confirmMove",confirm,actions.grant()));
            actions.begin("s","approve-"+checks,answer);actions.interpretIntent(intent(answer,"approve",answer,"all",proposal.get("proposalId").getAsString(),false,"move"));
            before=ui.preparedCount;actions.handle("library.confirmMove",confirm,actions.grant());actions.handle("library.confirmMove",confirm,actions.grant());
            check(PdfLibraryOrganization.load(root).folder(proposal.get("sourceId").getAsString()).parentId().equals(destination.id())&&ui.preparedCount==before+1,"AI-approved natural variation executes exact immutable proposal once");
            denied("library_permission_required",()->actions.handle("library.proposeMove",move(parent.id(),destination.id(),revision(actions)),actions.grant()));
        }
        for(String decision:List.of("reject","none")){
            JsonObject proposal=pending(actions,ui,root,destination.id(),"중단자료"+checks,"stop-proposal-"+checks);String answer=decision.equals("reject")?"그건 하지 않는 게 좋겠어":"오늘 날씨는 어때?";
            actions.begin("s","stop-"+checks,answer);actions.interpretIntent(intent(answer,decision,answer,"all","",false));check(actions.context().has("pendingMove")==decision.equals("none")&&actions.scopes().isEmpty(),"explicit cancellation clears a proposal; read-only chat preserves it without authority");
            if(decision.equals("none")){
                actions.begin("s","resume-"+checks,"그 이동 진행해");actions.interpretIntent(intent("그 이동 진행해","approve","그 이동 진행해","all",proposal.get("proposalId").getAsString(),false,"move"));
                actions.handle("library.confirmMove",confirm(proposal),actions.grant());continue;
            }
            actions.begin("s","after-stop-"+checks,"엉 맞어");denied("library_permission_required",()->actions.interpretIntent(intent("엉 맞어","approve","엉 맞어","all",proposal.get("proposalId").getAsString(),false,"move")));
        }
        JsonObject conditionalProposal=pending(actions,ui,root,destination.id(),"조건자료","conditional-proposal");actions.begin("s","conditional","백업되면 진행해");actions.interpretIntent(intent("백업되면 진행해","clarify","백업되면 진행해","all","",false));check(actions.context().has("pendingMove")&&actions.scopes().isEmpty(),"conditional/unclear decision retains proposal without execution");
        denied("library_permission_required",()->actions.handle("library.confirmMove",confirm(conditionalProposal),actions.grant()));
        actions.begin("s","tampered-token","진행해");denied("library_permission_required",()->actions.interpretIntent(intent("진행해","approve","진행해","all","wrong-token",false,"move")));
        JsonObject quotedProposal=pending(actions,ui,root,destination.id(),"인용자료","quoted-proposal");String quoted="‘엉 맞어’라는 표현을 설명해 줘";actions.begin("s","quoted",quoted);String token=quotedProposal.get("proposalId").getAsString();
        denied("library_permission_required",()->actions.interpretIntent(intent(quoted,"approve","엉 맞어","all",token,false,"move")));check(actions.scopes().isEmpty(),"quoted text is not direct authorization evidence");
        actions.begin("other-chat","cross-session","진행해");denied("library_permission_required",()->actions.interpretIntent(intent("진행해","approve","진행해","all",token,false,"move")));
        JsonObject delayedProposal=pending(actions,ui,root,destination.id(),"나중승인자료","delayed-proposal");var pendingAt=AssistantLibraryActions.class.getDeclaredField("pendingAt");pendingAt.setAccessible(true);pendingAt.setLong(actions,System.currentTimeMillis()-3_600_001);
        actions.begin("s","delayed","진행해");String delayedToken=delayedProposal.get("proposalId").getAsString();actions.interpretIntent(intent("진행해","approve","진행해","all",delayedToken,false,"move"));
        actions.handle("library.confirmMove",confirm(delayedProposal),actions.grant());check(PdfLibraryOrganization.load(root).folder(delayedProposal.get("sourceId").getAsString()).parentId().equals(destination.id()),"elapsed time alone does not discard an exact unchanged proposal");
        ui.folder="";request(actions,"scope","현재 화면의 폴더1을 보고 싶어","current",false,"open");String scopeRev=revision(actions);ui.folder=other.id();actions.handle("library.open",args("folder",parent.id(),scopeRev),actions.grant());check(ui.folder.equals(parent.id()),"later navigation does not cancel the original explicit open");
        actions.begin("s","joined-evidence","엉‘가짜’맞어");denied("library_permission_required",()->actions.interpretIntent(intent("엉‘가짜’맞어","request","엉맞어","all","",false,"open")));
        actions.begin("s","question-mismatch","아무 것도 하지마");denied("library_permission_required",()->actions.interpretIntent(intent("옮겨줘","request","옮겨줘","all","",false,"move")));
        System.out.println("AssistantLibraryActionsTest OK · "+checks+" checks");
    }
}
