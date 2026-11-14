package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Counterexamples for self-induced stale revisions and referenced cancellation. */
public final class AssistantOwnRevisionTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private interface Work{void run()throws Exception;}
    private static void denied(String code,Work work)throws Exception{try{work.run();throw new AssertionError("expected "+code);}catch(AssistantLibraryActions.Denied failure){check(code.equals(failure.code),failure.code);}}
    private static JsonObject obj(String... pairs){return AssistantSourceFolderTest.obj(pairs);}
    private static JsonObject create(String parent,String name,String revision){return obj("parentId",parent,"name",name,"expectedRevision",revision);}
    private static String created(JsonObject result){return result.getAsJsonArray("createdFolders").get(0).getAsJsonObject().get("id").getAsString();}
    private static JsonObject intent(String question,String decision,String token,String... ops){
        JsonObject out=obj("question",question,"decision",decision,"evidence",question,"sourceScope","all","proposalId","","clarificationId",token);out.addProperty("selectionAll",false);
        JsonArray operations=new JsonArray();for(String op:ops)operations.add(op);out.add("operations",operations);return out;
    }
    private static void begin(AssistantSourceFolderTest.Fixture f,String turn,String... ops)throws Exception{
        f.host.begin("session",turn,"폴더를 나누고 자료를 정리해줘");JsonObject i=intent("폴더를 나누고 자료를 정리해줘","request","",ops);i.addProperty("sourceFolderId",f.source);f.host.interpretIntent(i);
    }
    public static void main(String[] args)throws Exception{
        for(boolean externalEdit:List.of(false,true))try(var f=new AssistantSourceFolderTest.Fixture(2,false)){
            String question="이 폴더 자료를 모을 폴더를 만들고 옮겨줘. 먼저 확인해줘";
            f.host.begin("session","pin-request",question);f.query(false);JsonObject ask=intent(question,"clarify","","create","move");ask.addProperty("sourceFolderId",f.source);f.host.interpretIntent(ask);f.host.finish("이 원본 자료를 새 모음에 넣을까요?");
            String token=f.host.context().getAsJsonObject("pendingRequest").get("clarificationId").getAsString();
            if(externalEdit)PdfLibraryStore.rename(f.root,f.inside.get(0),"사용자가 바꿈.pdf");
            f.ui.folder=f.other;f.host.begin("session","pin-approval","그대로 진행해줘");
            String revision=f.host.context().get("revision").getAsString();f.host.interpretIntent(intent("그대로 진행해줘","request",token,"create","move"));
            JsonObject create=create(f.source,"재개 모음",revision);
            if(externalEdit){
                denied("library_stale",()->f.host.handle("library.createFolder",create,f.host.grant()));check(f.ui.writes==0,"catalog changes must not reuse old observations");
                f.query(false);
            }
            String destination=created(f.host.handle("library.createFolder",create,f.host.grant()));
            JsonObject move=f.ids(f.library.snapshot().get("revision").getAsString(),f.inside);move.addProperty("destinationId",destination);
            f.host.handle("library.proposeMove",move,f.host.grant());
            check(f.inside.stream().allMatch(id->{try{return f.location(id).equals(destination);}catch(Exception e){throw new RuntimeException(e);}}),"same catalog continuation remains executable after navigation; changed catalog needs a real query");
            check(f.location(f.outside).isEmpty(),"resumed task cannot include outside files");
        }
        try(var f=new AssistantSourceFolderTest.Fixture(3,false)){
            begin(f,"chain","create","move","rename");String original=f.query(true);
            JsonObject command=create(f.source,"중간고사",original),one=f.host.handle("library.createFolder",command,f.host.grant());String middle=one.get("revision").getAsString();
            String mid=created(one),fin=created(f.host.handle("library.createFolder",create(f.source,"기말고사",original),f.host.grant()));
            check(!mid.equals(fin)&&f.ui.writes==2,"same-query two-folder batch must complete");
            check(command.get("expectedRevision").getAsString().equals(original),"normalization must not modify caller arguments");
            check(created(f.host.handle("library.createFolder",command,f.host.grant())).equals(mid)&&f.ui.writes==2,"replay must not duplicate creation");
            JsonObject move=f.ids(original,List.of(f.inside.get(0)));move.addProperty("destinationId",mid);f.host.handle("library.proposeMove",move,f.host.grant());
            move=f.ids(middle,List.of(f.inside.get(1)));move.addProperty("destinationId",fin);f.host.handle("library.proposeMove",move,f.host.grant());
            check(f.location(f.inside.get(0)).equals(mid)&&f.location(f.inside.get(1)).equals(fin),"original and intermediate own revisions support sequential moves");
            JsonObject rename=obj("expectedRevision",original);JsonArray changes=new JsonArray();changes.add(obj("kind","document","id",f.inside.get(2),"name","정리.pdf"));rename.add("changes",changes);f.host.handle("library.rename",rename,f.host.grant());
            check(AssistantLibrary.find(f.library.snapshot(),"document",f.inside.get(2)).get("name").getAsString().equals("정리.pdf"),"mixed mutation types share the verified chain");
            String before=f.library.snapshot().toString();JsonObject outside=f.ids(original,List.of(f.outside));outside.addProperty("destinationId",mid);
            denied("library_scope_changed",()->f.host.handle("library.proposeMove",outside,f.host.grant()));check(before.equals(f.library.snapshot().toString()),"own revisions never widen source scope");
            denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"잘못된버전","bogus"),f.host.grant()));
            begin(f,"next-turn","create");f.query(true);denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"지난턴",original),f.host.grant()));
        }
        try(var f=new AssistantSourceFolderTest.Fixture(2,false)){
            begin(f,"external-edit","create");String original=f.query(true);f.host.handle("library.createFolder",create(f.source,"첫생성",original),f.host.grant());
            String ownHead=f.library.snapshot().get("revision").getAsString();PdfLibraryStore.rename(f.root,f.inside.get(0),"사람이 바꾼 이름.pdf");String before=f.library.snapshot().toString();
            for(String old:List.of(original,ownHead))denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"덮어쓰기",old),f.host.grant()));
            check(before.equals(f.library.snapshot().toString()),"external edits interrupt the chain without writes");
            String fresh=f.query(true);f.host.handle("library.createFolder",create(f.source,"새조회후생성",fresh),f.host.grant());
            denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"끊어진버전재사용",original),f.host.grant()));
            f.host.handle("library.createFolder",create(f.source,"새체인후속",fresh),f.host.grant());check(f.ui.writes==3,"a fresh query can start a new own-only chain");
        }
        for(boolean beforeSave:List.of(false,true))try(var f=new AssistantSourceFolderTest.Fixture(1,false)){
            begin(f,"save-race","create");String original=f.query(true);
            Runnable edit=()->{try{PdfLibraryStore.rename(f.root,f.inside.get(0),"저장사이외부수정.pdf");}catch(Exception e){throw new RuntimeException(e);}};
            if(beforeSave)f.ui.beforeSave=edit;else f.ui.afterSave=edit;
            if(beforeSave)denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"첫폴더",original),f.host.grant()));
            else f.host.handle("library.createFolder",create(f.source,"첫폴더",original),f.host.grant());
            f.ui.beforeSave=()->{};f.ui.afterSave=()->{};
            denied("library_stale",()->f.host.handle("library.createFolder",create(f.source,"잘못된후속",original),f.host.grant()));
            check(AssistantLibrary.find(f.library.snapshot(),"document",f.inside.get(0)).get("name").getAsString().equals("저장사이외부수정.pdf"),"save-boundary edit is preserved");
            check(f.ui.writes==(beforeSave?0:1),"save-boundary race cannot authorize subsequent writes");
        }
        try(var f=new AssistantSourceFolderTest.Fixture(1,false)){
            f.host.begin("session","pending","분류 전에 물어봐");f.host.interpretIntent(intent("분류 전에 물어봐","clarify","","create","move"));f.host.finish("어떤 폴더로 나눌까요?");
            String token=f.host.context().getAsJsonObject("pendingRequest").get("clarificationId").getAsString();String before=f.library.snapshot().toString();
            f.host.begin("session","bad-cancel","취소해");denied("library_permission_required",()->f.host.interpretIntent(intent("취소해","reject","wrong")));
            check(f.host.context().has("pendingRequest"),"wrong cancellation token must preserve the real pending task");
            JsonObject bad=intent("취소해","reject",token,"move");deniedIllegal(()->f.host.interpretIntent(bad));
            f.host.interpretIntent(intent("취소해","reject",token));check(!f.host.context().has("pendingRequest")&&f.host.scopes().isEmpty(),"referenced cancel clears task without authority");
            denied("library_permission_required",()->f.host.handle("library.createFolder",create("","취소후쓰기",f.query(true)),f.host.grant()));
            f.host.begin("session","late-approval","그대로 해줘");denied("library_permission_required",()->f.host.interpretIntent(intent("그대로 해줘","request",token,"create")));
            for(boolean named:List.of(false,true)){
                f.host.begin("session","fresh-looking-"+named,"그대로 해줘");JsonObject resurrect=intent("그대로 해줘","request","","create","move");if(named)resurrect.addProperty("sourceFolderId",f.source);f.host.interpretIntent(resurrect);
                denied("library_permission_required",()->f.host.handle("library.createFolder",create(f.source,"중간고사",f.query(true)),f.host.grant()));
                check(f.host.context().has("cancelledRequest")&&before.equals(f.library.snapshot().toString()),"cancelled task cannot be resurrected as a fresh request without a token");
            }
            for(String operation:List.of("rename","trash","move")){
                f.host.begin("session","resurrect-"+operation,"그대로 해줘");JsonObject resurrect=intent("그대로 해줘","request","",operation);resurrect.addProperty("sourceFolderId",f.source);f.host.interpretIntent(resurrect);
                String revision=f.query(true);JsonObject command=f.ids(revision,List.of(f.inside.get(0)));String tool="library.trash";
                if(operation.equals("move")){command.addProperty("destinationId",f.destination);tool="library.proposeMove";}
                else if(operation.equals("rename")){command=obj("expectedRevision",revision);JsonArray changes=new JsonArray();changes.add(obj("kind","document","id",f.inside.get(0),"name","재시작하면안됨.pdf"));command.add("changes",changes);tool="library.rename";}
                final JsonObject attempt=command;final String targetTool=tool;
                denied("library_permission_required",()->f.host.handle(targetTool,attempt,f.host.grant()));
                check(before.equals(f.library.snapshot().toString()),"cancellation barrier covers every mutation type");
            }
            f.host.begin("different-session","other-cancel","취소해");denied("library_permission_required",()->f.host.interpretIntent(intent("취소해","reject",token)));
            check(before.equals(f.library.snapshot().toString())&&f.ui.writes==0,"all cancellation variants preserve documents");
        }
        try(var f=new AssistantSourceFolderTest.Fixture(1,false)){
            f.host.begin("session","cancel-new","정리 전에 물어봐");f.host.interpretIntent(intent("정리 전에 물어봐","clarify","","create"));
            f.host.begin("session","cancel-new-2","취소해");f.host.interpretIntent(intent("취소해","reject",""));
            f.host.begin("session","new-direct","새공부 폴더 하나 만들어줘");f.host.interpretIntent(intent("새공부 폴더 하나 만들어줘","request","","create"));
            f.host.handle("library.createFolder",create("","새공부",f.query(true)),f.host.grant());
            check(f.ui.writes==1&&!f.host.context().has("cancelledRequest"),"a new directly named task remains authorized after cancellation");
        }
        try(var f=new AssistantSourceFolderTest.Fixture(1,false)){
            f.host.begin("session","proposal","이동 전에 확인해줘");JsonObject prepare=intent("이동 전에 확인해줘","clarify","","move");prepare.addProperty("sourceFolderId",f.source);f.host.interpretIntent(prepare);
            JsonObject move=f.ids(f.query(true),List.of(f.inside.get(0)));move.addProperty("destinationId",f.destination);
            try{f.host.handle("library.proposeMove",move,f.host.grant());throw new AssertionError("missing confirmation");}catch(AssistantLibraryActions.Denied expected){check(expected.code.equals("confirmation_required"),"prepare immutable proposal");}
            String proposal=f.host.context().getAsJsonObject("pendingMove").get("proposalId").getAsString();
            f.host.begin("session","proposal-cancel","그 이동 취소해줘");JsonObject reject=intent("그 이동 취소해줘","reject","");reject.addProperty("proposalId","wrong");
            denied("library_permission_required",()->f.host.interpretIntent(reject));check(f.host.context().has("pendingMove"),"wrong move token preserves proposal");
            reject.addProperty("proposalId",proposal);f.host.interpretIntent(reject);
            check(!f.host.context().has("pendingMove")&&!f.host.context().has("pendingRequest")&&f.ui.writes==0,"exact move token cancels all pending continuation state without writing");
            f.host.begin("session","proposal-late","응 진행해");JsonObject approve=intent("응 진행해","approve","","move");approve.addProperty("proposalId",proposal);
            denied("library_permission_required",()->f.host.interpretIntent(approve));
        }
        try(var f=new AssistantSourceFolderTest.Fixture(2,true)){
            f.begin("trash",false);JsonObject trash=f.ids(f.query(false),List.of(f.inside.get(0)));
            denied("library_ambiguous",()->f.host.handle("library.trash",trash,f.host.grant()));
            String token=f.host.context().getAsJsonObject("pendingClarification").get("clarificationId").getAsString();
            f.host.begin("session","choice-cancel","그 삭제 취소해줘");f.host.interpretIntent(intent("그 삭제 취소해줘","reject",token));
            check(!f.host.context().has("pendingClarification")&&f.ui.writes==0,"candidate-choice cancellation accepts its exact token without deleting anything");
        }
        System.out.println("AssistantOwnRevisionTest OK · "+checks+" checks");
    }
    private static void deniedIllegal(Work work)throws Exception{try{work.run();throw new AssertionError("invalid reject operations accepted");}catch(IllegalArgumentException expected){checks++;}}
}
