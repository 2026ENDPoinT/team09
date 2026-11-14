package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Host-owned capabilities and confirmation state for the virtual document library. */
final class AssistantLibraryActions {
    private static final Set<String> TOOLS=Set.of("library.query","library.open","library.createFolder","library.rename","library.trash","library.proposeMove","library.confirmMove");
    private final AssistantLibrary library;
    private final AssistantLibraryUi ui;
    private final java.util.function.Supplier<JsonObject> recoveryContext;
    private final Map<String,JsonObject> observed=new HashMap<>();
    private String session="",turn="",question="",grant="",scopes="",pendingGrant="",pendingScopes="";
    private JsonObject requestView=new JsonObject();
    private String sourceFolderId;
    private long pendingAt;
    private boolean currentScope,rootSource,approved,mutated,awaitingChoice,approvalUnclear,approvalMissing,selectionAll,moveConfirmationOnly;
    private Set<String> operations=Set.of();
    private String interpretedIntent="",executingTool="";
    private JsonObject executingArgs;
    private Choice clarification,activeChoice;
    record Choice(String id,String session,long at,String operation,JsonObject arguments,boolean source,String kind,Set<String> candidates,String revision,JsonObject view,boolean currentScope,boolean rootSource,String sourceFolderId,String quote,JsonArray candidateRows){}
    private Continuation pendingRequest;
    private JsonObject cancelledRequest;
    private boolean freshTaskGrounded;
    private String confirmationQuestion="",discussionToken="",turnDecision="";
    private final JsonArray taskDiscussion=new JsonArray();
    record Continuation(String id,String session,String quote,Set<String> operations,JsonObject view,boolean currentScope,boolean rootSource,String sourceFolderId,boolean selectionAll,JsonArray targets,String revision){}
    private Proposal pending;
    private final Map<String,JsonObject> turnResults=new HashMap<>();
    private final Set<String> ownRevisions=new HashSet<>();
    private String ownRevisionHead="";
    record Proposal(String id,String session,String revision,JsonArray changes,JsonObject summary,String viewToken,boolean currentScope,String quote){}
    static final class Denied extends IllegalArgumentException {
        final String code,proposalId;
        Denied(String code,String message){this(code,message,"");}
        Denied(String code,String message,String proposalId){super(message);this.code=code;this.proposalId=proposalId;}
    }
    AssistantLibraryActions(AssistantLibrary library,AssistantLibraryUi ui){this(library,ui,null);}
    AssistantLibraryActions(AssistantLibrary library,AssistantLibraryUi ui,java.util.function.Supplier<JsonObject> recoveryContext){this.library=library;this.ui=ui;this.recoveryContext=recoveryContext;}
    synchronized boolean hasOperation(String id)throws Exception{return library.hasOperation(id);}
    synchronized JsonObject undoInfo()throws Exception{return library.undoInfo();}
    synchronized JsonObject undo(String operationId,String target)throws Exception{
        Object prepared=ui.prepareMutation(new JsonArray());JsonObject result;
        try{result=library.undo(operationId,target);}catch(Exception failure){ui.cancelMutation(prepared);throw failure;}mutated=true;
        return finishMutation(prepared,result);
    }
    static boolean supports(String tool){return TOOLS.contains(tool);}
    private static String plain(String text){return text.replaceAll("(?s)```.*?```","").replaceAll("(?m)^\\s*>.*$","").replaceAll("`[^`]*`|\"[^\"]*\"|'[^']*'|“[^”]*”|‘[^’]*’","");}
    synchronized void begin(String sessionId,String turnId,String text){
        boolean same=session.equals(sessionId);session=sessionId;turn=turnId;question=text;grant="";scopes="";approved=false;mutated=false;approvalUnclear=false;approvalMissing=false;selectionAll=false;moveConfirmationOnly=false;
        operations=Set.of();interpretedIntent="";turnDecision="";discussionToken="";activeChoice=null;observed.clear();turnResults.clear();ownRevisions.clear();ownRevisionHead="";freshTaskGrounded=false;
        if(!same)pendingRequest=null;
        // Navigation and elapsed time are not cancellation. Exact IDs/session and
        // catalog revisions still validate a later human choice before any write.
        if(!same){clearPending();confirmationQuestion="";taskDiscussion.asList().clear();cancelledRequest=null;}
        if(clarification!=null&&!session.equals(clarification.session()))clarification=null;
        try{requestView=ui.viewContext();requestView.remove("visibleItems");}catch(Exception failure){requestView=new JsonObject();}
        currentScope=false;rootSource=false;sourceFolderId=null;
    }
    private void clearPending(){pending=null;pendingGrant="";pendingScopes="";awaitingChoice=false;}
    /** AI interprets meaning; this endpoint checks provenance and native capability bounds. */
    synchronized JsonObject interpretIntent(JsonObject args)throws Exception {
        keys(args,Set.of("question","decision","evidence","operations","sourceScope","sourceFolderId","proposalId","clarificationId","selectionAll"));
        String current=required(args,"question",2000,true),decision=choice(args,"decision",Set.of("request","approve","reject","clarify","none"));
        String evidence=required(args,"evidence",2000,true),source=choice(args,"sourceScope",Set.of("all","current","root")),proposalId=required(args,"proposalId",80,true),clarificationId=required(args,"clarificationId",80,true);
        String named=args.has("sourceFolderId")&&!args.get("sourceFolderId").isJsonNull()?required(args,"sourceFolderId",128,false):null;
        if(named!=null&&!source.equals("all"))throw new Denied("library_scope_changed","원본 폴더와 화면 범위를 동시에 바꿀 수 없어요.");
        if(!args.has("selectionAll")||!args.get("selectionAll").isJsonPrimitive()||!args.getAsJsonPrimitive("selectionAll").isBoolean())throw new IllegalArgumentException("전체 선택 판단 값을 확인해 주세요.");
        if(!args.has("operations")||!args.get("operations").isJsonArray()||args.getAsJsonArray("operations").size()>5)throw new IllegalArgumentException("작업 종류를 확인해 주세요.");
        Set<String> requested=new HashSet<>();for(JsonElement entry:args.getAsJsonArray("operations")){
            if(!entry.isJsonPrimitive()||!entry.getAsJsonPrimitive().isString()||!Set.of("open","create","move","rename","trash").contains(entry.getAsString())||!requested.add(entry.getAsString()))throw new IllegalArgumentException("허용된 작업 종류를 한 번씩만 지정해 주세요.");
        }
        if(!question.equals(current))throw new Denied("library_permission_required","현재 사용자 요청과 판단 근거가 달라 실행하지 않았어요.");
        String canonical=canonical(args);
        if(!interpretedIntent.isEmpty()){
            if(!interpretedIntent.equals(canonical))throw new Denied("library_permission_required","이번 요청의 의미 판단은 이미 정해졌어요.");
            JsonObject result=new JsonObject();result.addProperty("decision",decision);result.addProperty("replayed",true);return result;
        }
        boolean actionable=decision.equals("request")||decision.equals("approve")||decision.equals("clarify")&&requested.contains("move");
        String directEvidence=plain(evidence).strip();
        if(actionable&&(directEvidence.isBlank()||!question.contains(evidence)||!plain(question).contains(directEvidence)))throw new Denied("library_permission_required","직접 입력한 요청의 근거가 없어 실행하지 않았어요.");
        if(!Set.of("approve","reject").contains(decision)&&!proposalId.isEmpty())throw new IllegalArgumentException("승인이나 취소 외의 판단에는 이전 이동안 토큰을 넣지 않아요.");
        if(decision.equals("reject")&&!proposalId.isEmpty()&&(pending==null||!session.equals(pending.session())||!proposalId.equals(pending.id())))
            throw new Denied("library_permission_required","취소할 이동안이 현재 대기 작업과 달라요.");
        if(decision.equals("request")&&requested.isEmpty()||Set.of("reject","none").contains(decision)&&!requested.isEmpty())throw new IllegalArgumentException("의미 판단과 작업 종류가 달라요.");
        if(decision.equals("approve")&&requested.stream().anyMatch(op->!op.equals("move")))throw new IllegalArgumentException("이전 이동안 승인으로 다른 작업을 실행할 수 없어요.");
        if(mutated)throw new Denied("library_permission_required","저장 후에 작업 권한을 바꿀 수 없어요.");
        Choice bound=null;Continuation continued=null;
        if(!clarificationId.isEmpty()){
            if(Set.of("none","reject").contains(decision)&&((pendingRequest!=null&&pendingRequest.id().equals(clarificationId)&&session.equals(pendingRequest.session()))||
                (clarification!=null&&clarification.id().equals(clarificationId)&&session.equals(clarification.session())))){
                // A reference records discussion only. It never grants any operation.
                discussionToken=clarificationId;
            }else
            if(pendingRequest!=null&&pendingRequest.id().equals(clarificationId)&&session.equals(pendingRequest.session())){
                if(!Set.of("request","clarify").contains(decision)||requested.isEmpty()||!pendingRequest.operations().containsAll(requested)||args.get("selectionAll").getAsBoolean()&&!pendingRequest.selectionAll())
                    throw new Denied("library_permission_required","이전 질문에서 맡긴 작업 범위만 이어서 실행할 수 있어요.");
                continued=pendingRequest;
            }else if(!(decision.equals("request")||decision.equals("clarify")&&requested.equals(Set.of("move")))||clarification==null||!clarification.id().equals(clarificationId)||!session.equals(clarification.session())||!requested.equals(Set.of(clarification.operation())))
                throw new Denied("library_permission_required","이전 선택 질문과 현재 작업이 달라 실행하지 않았어요.");
            else bound=clarification;
        }
        if(decision.equals("request")){
            Choice old=bound;
            if(old!=null){
                activeChoice=old;grant=old.quote()+"\n후속 선택: "+question;requestView=old.view().deepCopy();currentScope=old.currentScope();rootSource=old.rootSource();
                operations=Set.of(old.operation());awaitingChoice=true;
            }else if(continued!=null){
                grant=continued.quote()+"\n후속 선택: "+question;requestView=continued.view().deepCopy();currentScope=continued.currentScope();rootSource=continued.rootSource();
                operations=Set.copyOf(requested);awaitingChoice=true;
                restoreContinuationObservations(continued);
            }else{
                pendingRequest=null;clarification=null;activeChoice=null;awaitingChoice=false;grant=question;operations=Set.copyOf(requested);currentScope=source.equals("current");rootSource=source.equals("root");
            }
            String inherited=old!=null?old.sourceFolderId():continued!=null?continued.sourceFolderId():null;
            if(inherited!=null&&named!=null&&!inherited.equals(named))throw new Denied("library_scope_changed","이전 요청에서 정한 원본 폴더를 바꿀 수 없어요.");
            if(inherited!=null&&!source.equals("all"))throw new Denied("library_scope_changed","이전 요청에서 지정한 원본 폴더 범위를 유지해 주세요.");
            sourceFolderId=inherited!=null?inherited:named;
            if(grant.length()>2000)throw new Denied("library_permission_required","이어지는 요청이 너무 길어요. 작업을 나눠 주세요.");
            scopes=(operations.contains("open")?"libraryOpen":"")+((operations.contains("create")||operations.contains("move")||operations.contains("rename")||operations.contains("trash"))?(operations.contains("open")?",libraryWrite":"libraryWrite"):"");
            selectionAll=args.get("selectionAll").getAsBoolean();pending=null;approved=false;
        }else if(decision.equals("approve")){
            if(pending==null||!session.equals(pending.session())||!pending.id().equals(proposalId)){
                clearPending();approvalMissing=true;throw new Denied("library_permission_required","승인할 이동안이 없거나 바뀌었어요. 원본과 목적지를 다시 확인해 주세요.");
            }
            approved=true;operations=Set.of("move");scopes="libraryWrite";grant=pending.quote()+"\n이동 승인: "+question;currentScope=pending.currentScope();
            sourceFolderId=pending.summary().has("sourceFolderId")&&!pending.summary().get("sourceFolderId").isJsonNull()?text(pending.summary(),"sourceFolderId"):null;
        }else if(decision.equals("clarify")){
            if(!requested.isEmpty()&&bound==null){
                if(continued==null){confirmationQuestion="";taskDiscussion.asList().clear();}
                JsonArray targets=new JsonArray();
                if(continued!=null)continued.targets().forEach(row->targets.add(row.deepCopy()));
                Set<String> known=new HashSet<>();for(JsonElement row:targets){JsonObject item=row.getAsJsonObject();known.add(text(item,"kind")+":"+text(item,"id"));}
                for(var row:observed.entrySet())if(known.add(row.getKey()))targets.add(row.getValue().deepCopy());
                JsonObject origin=continued==null?requestView:continued.view();
                String request=continued==null?question:continued.quote()+"\n후속 조건: "+question;
                if(request.length()>2000)throw new Denied("library_permission_required","이어지는 요청이 너무 길어요. 작업을 나눠 주세요.");
                pendingRequest=new Continuation(continued==null?UUID.randomUUID().toString():continued.id(),session,request,Set.copyOf(requested),origin.deepCopy(),continued==null?source.equals("current"):continued.currentScope(),continued==null?source.equals("root"):continued.rootSource(),continued==null?named:continued.sourceFolderId(),continued==null?args.get("selectionAll").getAsBoolean():continued.selectionAll(),targets,continued==null?text(library.snapshot(),"revision"):continued.revision());
            }
            if(requested.contains("move")){
                // A destination question prepares a concrete immutable proposal, never a write.
                scopes="libraryWrite";grant=question;operations=Set.of("move");moveConfirmationOnly=true;approved=false;pending=null;
                if(bound!=null){activeChoice=bound;grant=bound.quote()+"\n후속 선택: "+question;requestView=bound.view().deepCopy();currentScope=bound.currentScope();rootSource=bound.rootSource();}
                else if(continued!=null){grant=continued.quote()+"\n후속 선택: "+question;requestView=continued.view().deepCopy();currentScope=continued.currentScope();rootSource=continued.rootSource();}
                else{clarification=null;activeChoice=null;currentScope=source.equals("current");rootSource=source.equals("root");}
                selectionAll=args.get("selectionAll").getAsBoolean();
                String inherited=bound!=null?bound.sourceFolderId():continued!=null?continued.sourceFolderId():null;
                if(inherited!=null&&(named!=null&&!inherited.equals(named)||!source.equals("all")))throw new Denied("library_scope_changed","이전 요청에서 지정한 원본 폴더 범위를 유지해 주세요.");
                sourceFolderId=inherited!=null?inherited:named;
            }else{scopes="";grant="";operations=Set.of();approvalUnclear=pending!=null;}

        }else{
            // Read-only chat and navigation do not revoke unfinished human requests.
            if(decision.equals("reject")){
                String cancelled=pendingRequest!=null?pendingRequest.quote():clarification!=null?clarification.quote():pending!=null?pending.quote():"";
                if(!cancelled.isEmpty()){cancelledRequest=new JsonObject();cancelledRequest.addProperty("request",cancelled);cancelledRequest.addProperty("status","cancelled");}
                clearPending();pendingRequest=null;clarification=null;confirmationQuestion="";taskDiscussion.asList().clear();
            }
            activeChoice=null;scopes="";grant="";operations=Set.of();
        }
        interpretedIntent=canonical;turnDecision=decision;
        JsonObject result=new JsonObject();result.addProperty("decision",decision);result.addProperty("replayed",false);return result;
    }
    synchronized String scopes(){return scopes;}
    synchronized String grant(){return grant;}
    synchronized void finish(String answer){
        if(pendingRequest==null&&clarification==null&&pending==null)return;
        if(turnDecision.equals("clarify"))confirmationQuestion=answer.substring(0,Math.min(4000,answer.length()));
        else if(turnDecision.equals("none")&&!discussionToken.isEmpty()){
            JsonObject exchange=new JsonObject();exchange.addProperty("question",question);
            exchange.addProperty("answer",answer.substring(0,Math.min(4000,answer.length())));
            taskDiscussion.add(exchange);
            while(taskDiscussion.size()>6)taskDiscussion.remove(0);
        }
    }
    synchronized JsonObject context() throws Exception {
        JsonObject catalog=library.snapshot(),out=ui.viewContext();out.addProperty("available",true);out.addProperty("semanticAuthorization",true);out.addProperty("authorizationQuote",grant);out.addProperty("moveConfirmationOnly",moveConfirmationOnly);out.add("revision",catalog.get("revision"));out.addProperty("rootId","");out.addProperty("rootPath","홈화면");
        if(cancelledRequest!=null)out.add("cancelledRequest",cancelledRequest.deepCopy());
        out.addProperty("sourceFolderId",sourceFolderId);
        out.add("requestView",requestView.deepCopy());out.addProperty("totalItems",catalog.get("total").getAsInt());
        JsonArray visible=new JsonArray();int visibleTotal=out.has("visibleItems")?out.getAsJsonArray("visibleItems").size():0;
        if(out.has("visibleItems"))for(JsonElement e:out.getAsJsonArray("visibleItems")){
            if(visible.size()>=100)break;
            JsonObject ref=e.getAsJsonObject(),item=AssistantLibrary.find(catalog,text(ref,"kind"),text(ref,"id"));
            if(item!=null){visible.add(item.deepCopy());observe(item);}
        }
        out.add("visibleItems",visible);out.addProperty("visibleTotal",visibleTotal);out.addProperty("visibleItemsTruncated",visibleTotal>visible.size());
        JsonArray breadcrumbs=new JsonArray();JsonObject currentFolder=AssistantLibrary.find(catalog,"folder",text(out,"currentFolderId"));
        if(currentFolder!=null){for(JsonElement ancestor:currentFolder.getAsJsonArray("ancestorIds")){
            if(ancestor.getAsString().isEmpty())continue;
            JsonObject folder=AssistantLibrary.find(catalog,"folder",ancestor.getAsString());if(folder!=null){breadcrumbs.add(folder.deepCopy());observe(folder);}
        }breadcrumbs.add(currentFolder.deepCopy());observe(currentFolder);}
        out.add("breadcrumbs",breadcrumbs);out.addProperty("currentFolderInTrash",currentFolder!=null&&(flag(currentFolder,"trashed")||flag(currentFolder,"systemTrash")));
        if(pending!=null){JsonObject summary=pending.summary().deepCopy();summary.addProperty("proposalId",pending.id());summary.addProperty("createdAt",pendingAt);summary.addProperty("approved",approved);summary.addProperty("approvalUnclear",approvalUnclear);out.add("pendingMove",summary);
            if(approvalUnclear)out.addProperty("permissionNotice","확실한 승인으로 파악되지 않아 아직 옮기지 않았어요. 파일 이동 기능은 사용할 수 있어요.\n"+pendingListing()+"\n위 항목을 ‘"+text(pending.summary().getAsJsonObject("destination"),"path")+"’ 폴더로 옮겨도 될까요?");
        }
        if(clarification!=null){
            JsonObject choice=new JsonObject();choice.addProperty("clarificationId",clarification.id());choice.addProperty("request",clarification.quote());choice.addProperty("operation",clarification.operation());choice.addProperty("sourceScope",clarification.rootSource()?"root":clarification.currentScope()?"current":"all");choice.addProperty("sourceFolderId",clarification.sourceFolderId());choice.addProperty("revision",clarification.revision());choice.add("requestView",clarification.view().deepCopy());choice.add("candidates",clarification.candidateRows().deepCopy());out.add("pendingClarification",choice);
        }
        if(pendingRequest!=null){
            JsonObject continuation=new JsonObject();continuation.addProperty("clarificationId",pendingRequest.id());continuation.addProperty("request",pendingRequest.quote());
            JsonArray ops=new JsonArray();pendingRequest.operations().stream().sorted().forEach(ops::add);continuation.add("operations",ops);
            continuation.addProperty("sourceScope",pendingRequest.rootSource()?"root":pendingRequest.currentScope()?"current":"all");
            continuation.addProperty("sourceFolderId",pendingRequest.sourceFolderId());
            continuation.addProperty("selectionAll",pendingRequest.selectionAll());continuation.add("requestView",pendingRequest.view().deepCopy());
            continuation.addProperty("revision",pendingRequest.revision());
            continuation.addProperty("targetsCurrent",text(catalog,"revision").equals(pendingRequest.revision()));
            continuation.addProperty("confirmationQuestion",confirmationQuestion);
            continuation.add("discussion",taskDiscussion.deepCopy());
            continuation.add("targets",pendingRequest.targets().deepCopy());out.add("pendingRequest",continuation);
        }
        for(String key:List.of("pendingClarification","pendingMove"))if(out.has(key)){
            out.getAsJsonObject(key).addProperty("confirmationQuestion",confirmationQuestion);
            out.getAsJsonObject(key).add("discussion",taskDiscussion.deepCopy());
        }
        out.addProperty("approvalMissing",approvalMissing);
        if(approvalMissing)out.addProperty("permissionNotice","파일 이동 기능은 사용할 수 있지만, 지금 이어서 승인할 이동안이 없어요. 옮길 파일과 목적지를 알려주시면 현재 위치를 확인해서 이어서 처리할게요.");
        return out;
    }
    synchronized JsonObject handle(String tool,JsonObject args,String suppliedQuote)throws Exception {
        try{return execute(tool,args,suppliedQuote);}
        catch(java.io.IOException failure){
            String message=failure.getMessage();
            if(message==null||!message.matches("(?s)^[가-힣].*"))message="파일 작업을 처리하지 못했어요. 현재 자료는 보존했어요.";
            String code=message.contains("변경됐")||message.contains("조회 버전")?"library_stale":"library_validation";
            throw new Denied(code,message);
        }
    }
    private JsonObject execute(String tool,JsonObject args,String suppliedQuote)throws Exception {
        if(tool.equals("library.query")){
            JsonObject result=library.query(args);for(JsonElement item:result.getAsJsonArray("items"))observe(item.getAsJsonObject());
            if(args.has("parentId")&&!args.get("parentId").isJsonNull()&&!args.get("parentId").getAsString().isEmpty()){
                JsonObject parent=AssistantLibrary.find(library.snapshot(),"folder",args.get("parentId").getAsString());
                if(parent!=null)observe(parent);
            }
            return result;
        }
        if(tool.equals("library.confirmMove"))return confirm(args,suppliedQuote);
        if(approved)throw new Denied("library_permission_required","승인한 이전 이동안만 실행할 수 있어요.");
        String operation=switch(tool){case "library.open"->"open";case "library.createFolder"->"create";case "library.proposeMove"->"move";case "library.rename"->"rename";case "library.trash"->"trash";default->"";};
        if(!operations.contains(operation))throw new Denied("library_permission_required","현재 요청에서 맡긴 작업 종류만 실행할 수 있어요.");
        require(tool.equals("library.open")?"libraryOpen":"libraryWrite",suppliedQuote);
        if(cancelledRequest!=null&&!freshTaskGrounded&&!tool.equals("library.open")&&!(tool.equals("library.proposeMove")&&moveConfirmationOnly)){
            // A fresh grant after cancellation must name a target in the new
            // human request, not borrow it from cancelled chat history.
            JsonObject catalog=library.snapshot();boolean grounded=directTarget(text(args,"name"));
            if(sourceFolderId!=null){JsonObject folder=AssistantLibrary.find(catalog,"folder",sourceFolderId);grounded|=folder!=null&&directTarget(text(folder,"name"));}
            for(JsonElement entry:catalog.getAsJsonArray("items")){
                JsonObject item=entry.getAsJsonObject();String id=text(item,"id");
                if(id.equals(text(args,"parentId"))||id.equals(text(args,"destinationId"))||moveIdsSafe(args).contains(id))grounded|=directTarget(text(item,"name"))||directTarget(id);
            }
            if(!grounded)throw new Denied("library_permission_required","앞선 작업은 취소됐어요. 새로 작업할 대상과 내용을 알려 주세요.");
            freshTaskGrounded=true;
        }
        String replayKey=actionKey(operation,args);if(turnResults.containsKey(replayKey))return turnResults.get(replayKey).deepCopy();
        checkChoice(operation,args);
        // A batch may use one query revision for several independent writes. Only
        // bridge revisions committed by this host in this turn, with no intervening
        // external edit. The store still checks the effective revision atomically.
        if(args.has("expectedRevision")&&ownRevisions.contains(text(args,"expectedRevision"))&&
            ownRevisionHead.equals(text(library.snapshot(),"revision"))){
            args=args.deepCopy();args.addProperty("expectedRevision",ownRevisionHead);
        }
        executingTool=operation;executingArgs=args.deepCopy();
        if(sourceFolderId!=null){
            JsonObject catalog=library.snapshot();JsonObject folder=item(catalog,"folder",sourceFolderId,false);
            unique(catalog,folder,false,false,false);
        }
        return switch(tool){
            case "library.open"->open(args);
            case "library.createFolder"->create(args);
            case "library.rename"->rename(args);
            case "library.trash"->trash(args);
            case "library.proposeMove"->propose(args);
            default->throw new IllegalArgumentException("지원하지 않는 파일 작업이에요.");
        };
    }
    private String pendingListing(){
        List<String> paths=new ArrayList<>();for(JsonElement entry:pending.summary().getAsJsonArray("sources")){if(paths.size()>=10)break;paths.add(text(entry.getAsJsonObject(),"path"));}return String.join("\n",paths);
    }
    private void observe(JsonObject item){observed.put(text(item,"kind")+":"+text(item,"id"),item.deepCopy());}
    private void restoreContinuationObservations(Continuation continuation)throws Exception{
        JsonObject catalog=library.snapshot();
        if(!text(catalog,"revision").equals(continuation.revision()))return;
        for(JsonElement entry:continuation.targets()){
            JsonObject previous=entry.getAsJsonObject();JsonObject current=AssistantLibrary.find(catalog,text(previous,"kind"),text(previous,"id"));
            if(current!=null&&text(current,"name").equals(text(previous,"name"))&&text(current,"parentId").equals(text(previous,"parentId")))observe(current);
        }
    }
    private boolean directTarget(String target){String name=AssistantLibrary.normalize(target).replaceAll("[.?!。？！]+$","");return !name.isEmpty()&&AssistantLibrary.normalize(grant).contains(name);}
    private static Set<String> moveIdsSafe(JsonObject args){Set<String> ids=new HashSet<>();for(String field:List.of("ids","changes"))if(args.has(field)&&args.get(field).isJsonArray())for(JsonElement item:args.getAsJsonArray(field))if(item.isJsonObject())ids.add(text(item.getAsJsonObject(),"id"));return ids;}
    private void require(String scope,String quote){if(!Arrays.asList(scopes.split(",")).contains(scope)||!grant.equals(quote))throw new Denied("library_permission_required","사용자가 직접 요청한 파일·폴더 작업만 실행할 수 있어요.");}
    // Source scope is bound once to requestView, never to the user's later screen.
    private static String viewKey(JsonObject view){return text(view,"currentFolderId")+"|"+text(view,"section")+"|"+text(view,"screen")+"|"+text(view,"search");}
    private JsonObject fresh(String revision)throws Exception {
        JsonObject catalog=library.snapshot();if(!text(catalog,"revision").equals(revision))throw new Denied("library_stale","파일이나 폴더 목록이 변경됐어요. 다시 조회한 뒤 작업을 확인해 주세요.");return catalog;
    }
    private JsonObject item(JsonObject catalog,String kind,String id,boolean source){
        if(kind.equals("folder")&&id.isEmpty()){JsonObject root=new JsonObject();root.addProperty("id","");root.addProperty("kind","folder");root.addProperty("name","홈화면");root.addProperty("path","홈화면");root.addProperty("parentId","");return root;}
        JsonObject node=AssistantLibrary.find(catalog,kind,id);
        if(node==null||!observed.containsKey(kind+":"+id))throw new Denied("library_stale","먼저 파일이나 폴더를 조회해 실제 대상을 확인해 주세요.");
        if(source&&(currentScope||rootSource)&&!text(node,"parentId").equals(rootSource?"":text(requestView,"currentFolderId")))throw new Denied("library_scope_changed","처음 요청한 폴더 밖의 항목은 이 요청으로 바꿀 수 없어요.");
        if(source&&sourceFolderId!=null&&!text(node,"parentId").equals(sourceFolderId))throw new Denied("library_scope_changed","지정한 원본 폴더 밖의 항목은 이 요청으로 바꿀 수 없어요.");
        return node;
    }
    /** Same-name entries require a human path/selection, never the model's first match. */
    private void unique(JsonObject catalog,JsonObject selected,boolean source,boolean wholeSelection){
        unique(catalog,selected,source,wholeSelection,true);
    }
    private boolean outsideSource(JsonObject node){
        String parent=sourceFolderId!=null?sourceFolderId:rootSource?"":currentScope?text(requestView,"currentFolderId"):null;
        return parent!=null&&!text(node,"parentId").equals(parent);
    }
    private void unique(JsonObject catalog,JsonObject selected,boolean source,boolean wholeSelection,boolean rememberChoice){
        String id=text(selected,"id"),kind=text(selected,"kind"),name=AssistantLibrary.normalize(text(selected,"name"));if(id.isEmpty())return;
        List<JsonObject> matches=new ArrayList<>();
        for(JsonElement e:catalog.getAsJsonArray("items")){JsonObject node=e.getAsJsonObject();if(!flag(selected,"trashed")&&flag(node,"trashed"))continue;if(text(node,"kind").equals(kind)&&AssistantLibrary.normalize(text(node,"name")).equals(name)){
            if(source&&outsideSource(node))continue;
            matches.add(node);
        }}
        if(matches.size()<2||wholeSelection)return;
        String reference=grant.replaceAll("\\s+","").toLowerCase(Locale.ROOT);
        if(activeChoice!=null&&activeChoice.source()==source&&activeChoice.kind().equals(kind)&&activeChoice.candidates().contains(id))return;
        List<JsonObject> located=matches.stream().filter(n->{
            String parent=text(n,"parentPath"),leaf=parent.contains(" > ")?parent.substring(parent.lastIndexOf(" > ")+3):parent;
            String parentName=leaf.replaceAll("\\s+","").toLowerCase(Locale.ROOT),itemName=AssistantLibrary.normalize(text(n,"name"));boolean tied=false;
            // A structural path qualification is distinct from granting an operation or approval.
            for(String relation:List.of("에있는","안에있는","안의","의","에서","에"))for(String label:List.of("","파일","폴더"))if(reference.contains(parentName+relation+label+itemName))tied=true;
            return reference.contains(text(n,"path").replaceAll("\\s+","").toLowerCase(Locale.ROOT))||tied||reference.contains(text(n,"id"));
        }).toList();
        if(located.size()==1&&text(located.get(0),"id").equals(id))return;
        JsonArray choicesData=new JsonArray();Set<String> choiceIds=new HashSet<>();for(JsonObject match:matches){choicesData.add(match.deepCopy());choiceIds.add(text(match,"id"));}
        if(rememberChoice)clarification=new Choice(UUID.randomUUID().toString(),session,System.currentTimeMillis(),executingTool,executingArgs.deepCopy(),source,kind,Set.copyOf(choiceIds),text(catalog,"revision"),requestView.deepCopy(),currentScope,rootSource,sourceFolderId,grant,choicesData);
        String choices=matches.stream().limit(12).map(n->text(n,"path")+" (구분 "+text(n,"id").substring(0,8)+")").collect(java.util.stream.Collectors.joining("\n"));
        awaitingChoice=true;
        throw new Denied("library_ambiguous","‘"+text(selected,"name")+"’ 이름의 "+(kind.equals("folder")?"폴더":"파일")+"이 "+matches.size()+"개 있어요. 어떤 항목을 말씀하셨나요?\n"+choices);
    }
    private JsonObject open(JsonObject args)throws Exception {
        keys(args,Set.of("kind","id","expectedRevision"));String kind=choice(args,"kind",Set.of("folder","document")),id=required(args,"id",128,true);
        JsonObject catalog=fresh(required(args,"expectedRevision",64,false));JsonObject current=AssistantLibrary.find(catalog,"folder",text(requestView,"currentFolderId"));
        boolean ancestor=kind.equals("folder")&&(id.isEmpty()||id.equals(text(requestView,"currentFolderId"))||current!=null&&current.getAsJsonArray("ancestorIds").contains(new JsonPrimitive(id)));
        JsonObject node=item(catalog,kind,id,!ancestor);unique(catalog,node,true,false);
        JsonObject result=(kind.equals("folder")?ui.navigateFolder(id):ui.openDocument(id)).toCompletableFuture().get(20,TimeUnit.SECONDS);
        result.addProperty("kind",kind);result.addProperty("path",text(node,"path"));result.addProperty("name",text(node,"name"));result.addProperty("alreadyOpen",text(result,"status").equals("already_open"));
        turnResults.put("open:"+kind+":"+id,result.deepCopy());pendingRequest=null;pendingGrant="";pendingScopes="";awaitingChoice=false;clarification=null;activeChoice=null;return result;
    }
    private JsonObject create(JsonObject args)throws Exception {
        keys(args,Set.of("parentId","name","expectedRevision"));
        String parent=required(args,"parentId",128,true),name=required(args,"name",200,false),revision=required(args,"expectedRevision",64,false);
        String key="create:"+parent+":"+name;
        if(turnResults.containsKey(key))return turnResults.get(key).deepCopy();
        JsonObject catalog=fresh(revision);JsonObject destination=item(catalog,"folder",parent,false);unique(catalog,destination,false,false);
        JsonObject change=new JsonObject();change.addProperty("operation","createFolder");change.addProperty("parentId",parent);change.addProperty("name",name);JsonArray changes=new JsonArray();changes.add(change);
        JsonObject result=apply("create:"+key,revision,changes);turnResults.put(key,result.deepCopy());pendingRequest=null;
        if(result.has("createdFolders"))for(JsonElement created:result.getAsJsonArray("createdFolders")){JsonObject node=AssistantLibrary.find(library.snapshot(),"folder",text(created.getAsJsonObject(),"id"));if(node!=null)observe(node);}
        if(activeChoice!=null){clarification=null;activeChoice=null;awaitingChoice=false;}
        return result;
    }
    private JsonObject rename(JsonObject args)throws Exception {
        keys(args,Set.of("changes","expectedRevision"));
        String revision=required(args,"expectedRevision",64,false);JsonObject catalog=fresh(revision);
        if(!args.has("changes")||!args.get("changes").isJsonArray()||args.getAsJsonArray("changes").isEmpty()||args.getAsJsonArray("changes").size()>100)throw new IllegalArgumentException("이름을 바꿀 항목은 한 번에 1~100개로 지정해 주세요.");
        JsonArray refs=args.getAsJsonArray("changes"),changes=new JsonArray();Set<String> touched=new HashSet<>();
        for(JsonElement entry:refs){
            if(!entry.isJsonObject())throw new IllegalArgumentException("이름 변경 항목 형식을 확인해 주세요.");
            JsonObject ref=entry.getAsJsonObject();keys(ref,Set.of("kind","id","name"));
            String kind=choice(ref,"kind",Set.of("folder","document")),id=required(ref,"id",128,false),name=required(ref,"name",200,false);
            if(!touched.add(kind+":"+id))throw new IllegalArgumentException("같은 항목의 이름을 두 번 지정할 수 없어요.");
            JsonObject node=item(catalog,kind,id,true);boolean allMatches=selectionAll;
            if(allMatches)for(JsonElement candidate:catalog.getAsJsonArray("items")){
                JsonObject same=candidate.getAsJsonObject();
                if(!text(same,"kind").equals(kind)||!AssistantLibrary.normalize(text(same,"name")).equals(AssistantLibrary.normalize(text(node,"name"))))continue;
                if(outsideSource(same))continue;
                boolean included=false;for(JsonElement selected:refs)if(text(selected.getAsJsonObject(),"kind").equals(kind)&&text(selected.getAsJsonObject(),"id").equals(text(same,"id")))included=true;
                if(!included){allMatches=false;break;}
            }
            unique(catalog,node,true,allMatches);
            JsonObject change=ref.deepCopy();change.addProperty("name",name);change.addProperty("operation","rename");changes.add(change);
        }
        JsonObject result=apply("rename:"+renameKey(args),revision,changes);
        turnResults.put(actionKey("rename",args),result.deepCopy());
        pendingRequest=null;clarification=null;activeChoice=null;awaitingChoice=false;return result;
    }
    /** Reversible deletion only; permanent deletion is deliberately not an assistant capability. */
    private JsonObject trash(JsonObject args)throws Exception {
        keys(args,Set.of("ids","expectedRevision"));String revision=required(args,"expectedRevision",64,false);
        JsonObject catalog=fresh(revision);
        if(!args.has("ids")||!args.get("ids").isJsonArray()||args.getAsJsonArray("ids").isEmpty()||args.getAsJsonArray("ids").size()>100)throw new IllegalArgumentException("휴지통으로 옮길 항목은 한 번에 1~100개로 지정해 주세요.");
        JsonArray refs=args.getAsJsonArray("ids"),changes=new JsonArray();Set<String> touched=new HashSet<>();
        // Validate the entire selection before preparing animations or writing anything.
        for(JsonElement entry:refs){
            if(!entry.isJsonObject())throw new IllegalArgumentException("휴지통 이동 항목 형식을 확인해 주세요.");
            JsonObject ref=entry.getAsJsonObject();keys(ref,Set.of("kind","id"));
            String kind=choice(ref,"kind",Set.of("folder","document")),id=required(ref,"id",128,false);
            if(!touched.add(kind+":"+id))throw new IllegalArgumentException("같은 항목을 두 번 지정할 수 없어요.");
            JsonObject node=item(catalog,kind,id,true);
            if(flag(node,"systemTrash")||flag(node,"trashed"))throw new Denied("library_manual_delete_required","휴지통 안의 항목은 직접 영구 삭제해 주세요. 휴지통에서 항목을 선택한 뒤 ‘영구 삭제하기’를 눌러 주세요. 이번 요청으로 변경한 항목은 없어요.");
            boolean allMatching=selectionAll;
            if(allMatching)for(JsonElement candidate:catalog.getAsJsonArray("items")){
                JsonObject same=candidate.getAsJsonObject();
                if(flag(same,"trashed")||!text(same,"kind").equals(kind)||!AssistantLibrary.normalize(text(same,"name")).equals(AssistantLibrary.normalize(text(node,"name"))))continue;
                if(outsideSource(same))continue;
                if(!moveIds(args).contains(kind+":"+text(same,"id"))){allMatching=false;break;}
            }
            unique(catalog,node,true,allMatching);
            JsonObject change=ref.deepCopy();change.addProperty("operation","trash");changes.add(change);
        }
        JsonObject result=apply(actionKey("trash",args),revision,changes);result.addProperty("trashedCount",refs.size());result.addProperty("destinationPath",PdfLibraryOrganization.load(library.root()).displayPath(PdfLibraryOrganization.TRASH_ID));
        turnResults.put(actionKey("trash",args),result.deepCopy());pendingRequest=null;clarification=null;activeChoice=null;awaitingChoice=false;pending=null;return result;
    }
    private static boolean flag(JsonObject object,String key){return object.has(key)&&object.get(key).getAsBoolean();}
    private JsonObject propose(JsonObject args)throws Exception {
        keys(args,Set.of("ids","destinationId","expectedRevision"));String revision=required(args,"expectedRevision",64,false),destinationId=required(args,"destinationId",128,true);
        String nativeKey="move:"+moveKey(args);
        if(turnResults.containsKey(nativeKey))return turnResults.get(nativeKey).deepCopy();
        JsonObject catalog=fresh(revision),destination=item(catalog,"folder",destinationId,false);unique(catalog,destination,false,false);
        if(!args.has("ids")||!args.get("ids").isJsonArray()||args.getAsJsonArray("ids").isEmpty()||args.getAsJsonArray("ids").size()>100)throw new IllegalArgumentException("이동할 항목은 한 번에 1~100개로 지정해 주세요.");
        boolean all=selectionAll;
        JsonArray changes=new JsonArray(),sources=new JsonArray();Set<String> touched=new HashSet<>();
        for(JsonElement element:args.getAsJsonArray("ids")){
            JsonObject ref=element.getAsJsonObject();keys(ref,Set.of("kind","id"));String kind=choice(ref,"kind",Set.of("folder","document")),id=required(ref,"id",128,false);
            if(!touched.add(kind+":"+id))throw new IllegalArgumentException("같은 항목을 두 번 지정할 수 없어요.");
            JsonObject node=item(catalog,kind,id,true);
            boolean allMatchingSelected=all;
            if(all)for(JsonElement candidate:catalog.getAsJsonArray("items")){
                JsonObject same=candidate.getAsJsonObject();
                if(!text(same,"kind").equals(kind)||!AssistantLibrary.normalize(text(same,"name")).equals(AssistantLibrary.normalize(text(node,"name"))))continue;
                if(outsideSource(same))continue;
                boolean included=false;for(JsonElement selected:args.getAsJsonArray("ids"))if(text(selected.getAsJsonObject(),"kind").equals(kind)&&text(selected.getAsJsonObject(),"id").equals(text(same,"id"))){included=true;break;}
                if(!included){allMatchingSelected=false;break;}
            }
            unique(catalog,node,true,allMatchingSelected);sources.add(node.deepCopy());
            if(text(node,"parentId").equals(destinationId))continue;
            if(kind.equals("folder")&&(id.equals(destinationId)||destination.has("ancestorIds")&&destination.getAsJsonArray("ancestorIds").contains(new JsonPrimitive(id))))throw new IllegalArgumentException("폴더를 자기 자신이나 하위 폴더로 옮길 수 없어요.");
            JsonObject change=new JsonObject();change.addProperty("operation","move");change.addProperty("kind",kind);change.addProperty("id",id);change.addProperty("parentId",destinationId);changes.add(change);
        }
        if(changes.isEmpty()){JsonObject out=new JsonObject();out.addProperty("alreadyThere",true);out.addProperty("destinationPath",text(destination,"path"));return out;}
        if(moveConfirmationOnly){
            JsonObject summary=new JsonObject();summary.add("sources",sources.deepCopy());summary.add("destination",destination.deepCopy());summary.addProperty("sourceFolderId",sourceFolderId);
            String proposalId=UUID.randomUUID().toString();pending=new Proposal(proposalId,session,revision,changes.deepCopy(),summary,viewKey(requestView),currentScope,grant);pendingAt=System.currentTimeMillis();approved=false;pendingRequest=null;
            String listing=sources.asList().stream().limit(12).map(e->text(e.getAsJsonObject(),"path")).collect(java.util.stream.Collectors.joining("\n"));
            throw new Denied("confirmation_required",listing+"\n위 항목을 ‘"+text(destination,"path")+"’ 폴더로 옮길까요?",proposalId);
        }
        JsonObject result=apply(nativeKey,revision,changes);result.addProperty("destinationPath",text(destination,"path"));result.addProperty("movedCount",changes.size());
        turnResults.put(nativeKey,result.deepCopy());pendingRequest=null;clarification=null;activeChoice=null;awaitingChoice=false;pending=null;approved=false;pendingGrant="";pendingScopes="";return result;
    }
    private JsonObject confirm(JsonObject args,String quote)throws Exception {
        keys(args,Set.of("proposalId"));String id=required(args,"proposalId",80,false);
        if(turnResults.containsKey("confirm:"+id)){require("libraryWrite",quote);return turnResults.get("confirm:"+id).deepCopy();}
        if(pending==null||!pending.id().equals(id)||!session.equals(pending.session())||!approved)throw new Denied("library_permission_required","이동 목적지를 먼저 확인하고 동의해 주세요.");
        require("libraryWrite",quote);
        fresh(pending.revision());JsonObject result=apply("move:"+pending.id(),pending.revision(),pending.changes());result.addProperty("destinationPath",text(pending.summary().getAsJsonObject("destination"),"path"));result.addProperty("movedCount",pending.changes().size());turnResults.put("confirm:"+id,result.deepCopy());pending=null;approved=false;operations=Set.of();pendingGrant="";pendingScopes="";return result;
    }
    private void checkChoice(String operation,JsonObject args)throws Exception {
        if(activeChoice==null)return;
        Choice choice=activeChoice;
        if(!session.equals(choice.session())||!choice.operation().equals(operation))throw new Denied("library_permission_required","이전 선택 요청의 범위를 벗어나 실행하지 않았어요.");
        fresh(choice.revision());JsonObject original=choice.arguments();
        boolean valid;
        if(operation.equals("open"))valid=text(args,"kind").equals(text(original,"kind"))&&choice.candidates().contains(text(args,"id"));
        else if(operation.equals("create"))valid=text(args,"name").equals(text(original,"name"))&&choice.candidates().contains(text(args,"parentId"));
        else if(operation.equals("rename")){
            Map<String,String> before=renameNames(original),after=renameNames(args);int selected=0;
            for(String id:choice.candidates()){
                String key=choice.kind()+":"+id;before.remove(key);
                if(after.containsKey(key)){after.remove(key);selected++;}
            }
            // Resolve target separately: candidate iteration order must not affect validation.
            String wanted=null;for(JsonElement entry:original.getAsJsonArray("changes")){JsonObject ref=entry.getAsJsonObject();if(text(ref,"kind").equals(choice.kind())&&choice.candidates().contains(text(ref,"id")))wanted=text(ref,"name");}
            boolean sameName=true;for(JsonElement entry:args.getAsJsonArray("changes")){JsonObject ref=entry.getAsJsonObject();if(text(ref,"kind").equals(choice.kind())&&choice.candidates().contains(text(ref,"id"))&&!Objects.equals(wanted,text(ref,"name")))sameName=false;}
            valid=selected==1&&before.equals(after)&&sameName&&args.getAsJsonArray("changes").size()==original.getAsJsonArray("changes").size();
        }
        else if(!choice.source())valid=choice.candidates().contains(text(args,"destinationId"))&&moveIds(args).equals(moveIds(original));
        else{
            Set<String> originalIds=moveIds(original),newIds=moveIds(args);String selectedKind=choice.kind();
            Set<String> candidates=new HashSet<>();choice.candidates().forEach(id->candidates.add(selectedKind+":"+id));
            Set<String> fixed=new HashSet<>(originalIds);fixed.removeAll(candidates);Set<String> actualFixed=new HashSet<>(newIds);actualFixed.removeAll(candidates);
            Set<String> selected=new HashSet<>(newIds);selected.retainAll(candidates);
            valid=text(args,"destinationId").equals(text(original,"destinationId"))&&fixed.equals(actualFixed)&&newIds.size()==originalIds.size()&&selected.size()==1;
        }
        if(!valid)throw new Denied("library_permission_required","이전 질문에서 확인한 후보와 작업 범위만 선택할 수 있어요.");
    }
    private static Set<String> moveIds(JsonObject args){Set<String> ids=new TreeSet<>();if(args.has("ids")&&args.get("ids").isJsonArray())for(JsonElement entry:args.getAsJsonArray("ids")){if(!entry.isJsonObject())throw new IllegalArgumentException("이동 항목 형식을 확인해 주세요.");JsonObject item=entry.getAsJsonObject();ids.add(text(item,"kind")+":"+text(item,"id"));}return ids;}
    private static Map<String,String> renameNames(JsonObject args){Map<String,String> names=new TreeMap<>();if(args.has("changes")&&args.get("changes").isJsonArray())for(JsonElement entry:args.getAsJsonArray("changes")){JsonObject ref=entry.getAsJsonObject();names.put(text(ref,"kind")+":"+text(ref,"id"),text(ref,"name"));}return names;}
    private static String renameKey(JsonObject args){return canonical(new Gson().toJsonTree(renameNames(args)));}
    private static String actionKey(String operation,JsonObject args){return switch(operation){case "open"->"open:"+text(args,"kind")+":"+text(args,"id");case "create"->"create:"+text(args,"parentId")+":"+text(args,"name");case "move"->"move:"+moveKey(args);case "rename"->"rename:"+renameKey(args);case "trash"->"trash:"+String.join(",",moveIds(args));default->"";};}
    private static String moveKey(JsonObject args){return text(args,"destinationId")+":"+String.join(",",moveIds(args));}
    private static String canonical(JsonElement value){
        if(value.isJsonObject()){List<String> parts=new ArrayList<>();value.getAsJsonObject().entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(e->parts.add(new JsonPrimitive(e.getKey())+":"+canonical(e.getValue())));return "{"+String.join(",",parts)+"}";}
        if(value.isJsonArray()){List<String> parts=new ArrayList<>();value.getAsJsonArray().forEach(e->parts.add(canonical(e)));return "["+String.join(",",parts)+"]";}return value.toString();
    }
    private JsonObject apply(String key,String revision,JsonArray changes)throws Exception {
        JsonObject result;JsonObject context;
        if(recoveryContext!=null)context=recoveryContext.get();else{context=new JsonObject();context.addProperty("session",session);context.addProperty("turn",turn);context.addProperty("request",grant);}
        Object prepared=ui.prepareMutation(changes);
        try{result=library.apply(hash(turn+":"+key),revision,changes,context);}catch(Exception failure){ui.cancelMutation(prepared);throw failure;}mutated=true;
        if(freshTaskGrounded)cancelledRequest=null;
        if(result.has("replayed")&&result.get("replayed").getAsBoolean()){ownRevisions.clear();ownRevisionHead="";}
        else{
            if(!revision.equals(ownRevisionHead))ownRevisions.clear();
            ownRevisions.add(revision);ownRevisionHead=text(result,"revision");ownRevisions.add(ownRevisionHead);
        }
        return finishMutation(prepared,result);
    }
    private JsonObject finishMutation(Object prepared,JsonObject result){
        try{return ui.finishMutation(prepared,result).toCompletableFuture().get(20,TimeUnit.SECONDS);}
        catch(Exception visualFailure){result.addProperty("animationCompleted",false);result.addProperty("notice","저장은 완료했지만 화면 전환을 마치지 못했어요. 저장 결과를 기준으로 안내해 주세요.");return result;}
    }
    synchronized boolean mutated(){return mutated;}
    private static String hash(String value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}
    private static void keys(JsonObject o,Set<String> allowed){for(String key:o.keySet())if(!allowed.contains(key))throw new IllegalArgumentException("허용되지 않은 파일 작업 필드예요.");}
    private static String text(JsonObject o,String key){JsonElement v=o.get(key);return v==null||v.isJsonNull()?"":v.getAsString();}
    private static String required(JsonObject o,String key,int max,boolean empty){JsonElement v=o.get(key);if(v==null||!v.isJsonPrimitive()||!v.getAsJsonPrimitive().isString()||v.getAsString().length()>max||!empty&&v.getAsString().isBlank())throw new IllegalArgumentException(key+" 값을 확인해 주세요.");return v.getAsString();}
    private static String choice(JsonObject o,String key,Set<String> choices){String v=required(o,key,30,false);if(!choices.contains(v))throw new IllegalArgumentException("항목 종류를 확인해 주세요.");return v;}
}
