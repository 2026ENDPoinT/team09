package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.AppPaths;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import java.util.function.Supplier;
import java.util.regex.Pattern;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Capability boundary. Model text never becomes a path, executable, prompt, or account write. */
final class AssistantLocal {
    private static final Gson JSON=new GsonBuilder().serializeNulls()
        .registerTypeAdapter(LocalDate.class,(JsonSerializer<LocalDate>)(v,t,c)->new JsonPrimitive(v.toString()))
        .registerTypeAdapter(LocalDateTime.class,(JsonSerializer<LocalDateTime>)(v,t,c)->new JsonPrimitive(v.toString())).create();
    private static final Set<String> MEMORY_KEYS=Set.of("preferredName","language","tone","communicationStyle","responseLength","notes");
    private static final Pattern STYLE_NUANCE=Pattern.compile("친근|친구처럼|친구같|편안|편하게|부드럽|따뜻|다정|딱딱|차분|담백|유머|농담|장난");
    private static final Pattern UNDO_INTENT=Pattern.compile("되돌려|되돌리|되돌릴|원상\\s*복구|원래대로|롤백|undo|직전.{0,20}취소|방금.{0,20}취소",Pattern.CASE_INSENSITIVE);
    private static final Pattern EXPLANATION=Pattern.compile("설명해|번역해|요약해|검토해|분석해|가능해|할\\s*수\\s*있|어떻게\\s*(해|하)|무슨\\s*뜻|어떤\\s*뜻|예문|예시|인젝션|프롬프트|시스템\\s*지침|API\\s*키",Pattern.CASE_INSENSITIVE);
    // Routing only: never grants or denies file permissions. Avoid a separate undo
    // classifier for apparent library turns; the main response interprets their intent.
    private static final Pattern LIBRARY_ROUTING_HINT=Pattern.compile("파일|폴더|문서|자료|홈\\s*화면|기출|보고\\s*있는\\s*화면");
    private final PlannerStore planner;
    private final AssistantMutationAuthority mutationAuthority=new AssistantMutationAuthority();
    private final Path memoryFile;
    private final Supplier<JsonObject> profile;
    private AssistantLibraryActions library;
    private final Map<String,Set<String>> observed=new HashMap<>();
    private long observedRevision=-1;
    private String question="",turn="",grant="",scope="",session="";
    private boolean seriesConfirmed;
    private int calls;
    private boolean undoWritten,recoveryInterpreted,personalizationReset;
    private JsonObject recoveryLimit;
    private String recoveryDecision="";
    private boolean mutated,plannerWritten,memoryWritten,cancelledTurn,mutationUncertain;
    private Set<String> approvedOperations=Set.of();
    private static final class LocalDenied extends IllegalArgumentException {
        final String code;
        LocalDenied(String code,String message){super(message);this.code=code;}
    }

    AssistantLocal(){this(new PlannerStore(),AppPaths.account().resolve("assistant/user-preferences.json"),AssistantLocal::accountProfile);}
    AssistantLocal(PlannerStore planner,Path memoryFile,Supplier<JsonObject> profile){this.planner=planner;this.memoryFile=memoryFile;this.profile=profile;}
    synchronized void attachLibrary(AssistantLibraryUi ui){attachLibrary(new AssistantLibrary(),ui);}
    synchronized void attachLibrary(AssistantLibrary store,AssistantLibraryUi ui){library=new AssistantLibraryActions(store,ui,()->{JsonObject context=recoveryContext();context.addProperty("request",library.grant());return context;});}
    synchronized void begin(String sessionId,String turnId,String text){begin(sessionId,turnId,text,null);}
    synchronized void begin(String sessionId,String turnId,String text,JsonArray history){
        mutationAuthority.begin(sessionId,turnId,text,history);
        approvedOperations=Set.of();session=sessionId;turn=turnId;question=text;calls=0;mutated=false;undoWritten=false;recoveryInterpreted=false;recoveryLimit=null;recoveryDecision="";mutationUncertain=false;plannerWritten=false;memoryWritten=false;seriesConfirmed=false;observed.clear();observedRevision=-1;
        // No word lists grant ordinary planner or personalization writes. The main
        // model response binds their meaning to this direct human turn before use.
        personalizationReset=false;cancelledTurn=false;scope="";grant="";
        String plain=text.replaceAll("(?s)```.*?```","").replaceAll("(?m)^\\s*>.*$","").replaceAll("`[^`]*`|\"[^\"]*\"|'[^']*'|“[^”]*”|‘[^’]*’","");
        if(!preferenceResetRequest(plain)&&!EXPLANATION.matcher(plain).find()&&UNDO_INTENT.matcher(plain).find()){scope="undo";grant=text;}
        if(library!=null){
            library.begin(sessionId,turnId,text);String extra=library.scopes();
            if(!extra.isEmpty()){scope=scope.isEmpty()?extra:scope+","+extra;grant=library.grant();}
        }
    }
    static boolean preferenceResetRequest(String text){
        boolean domain=Pattern.compile("호칭|이름|별명|말투|어조|언어|존댓말|반말|선호|개인화|맞춤\\s*지침|메모리|기억").matcher(text).find();
        boolean reset=Pattern.compile("취소|해제|철회|초기화|삭제|지워|지우|잊어|기본값|기본\\s*(설정|상태|호칭|말투)\\s*(으로|로)|원래\\s*(설정|호칭|말투)\\s*(으로|로)").matcher(text).find();
        return domain&&reset;
    }
    static boolean preferenceRequest(String text){
        boolean domain=Pattern.compile("호칭|이름|별명|부르|불러|말투|어조|언어|존댓말|반말|답변|응답").matcher(text).find();
        boolean request=Pattern.compile("(?:해줘|해줭|해주세요|하자|하죠|해요|바꾸자|바꿔(?:줘|주세요)?|불러(?:줘|주세요)?|부르자|써줘|사용해(?:줘|주세요)?)(?:[.!。~\\s]|$)").matcher(text).find();
        return domain&&request;
    }
    synchronized void finish(String answer){mutationAuthority.finish(plannerWritten||memoryWritten,answer);if(library!=null)library.finish(answer);}
    synchronized JsonObject handle(JsonObject request){
        JsonObject reply=new JsonObject();reply.addProperty("id",request.has("id")?request.get("id").getAsString():"");
        boolean uncertainBefore=mutationUncertain;
        try{
            if(++calls>32)throw new IllegalArgumentException("한 번의 대화에서 처리할 수 있는 작업 수를 넘었어요.");
            keys(request,Set.of("type","id","tool","arguments","authorizationQuote"));
            String tool=str(request,"tool",80);JsonObject args=obj(request,"arguments");
            JsonObject result=switch(tool){
                case "context.get"->{
                    keys(args,Set.of());JsonObject out=new JsonObject();out.add("profile",profile.get());out.add("personalization",readMemory());
                    JsonObject libraryContext=null;
                    if(library!=null)try{libraryContext=library.context();out.add("library",libraryContext);}
                    catch(Exception unavailable){JsonObject status=new JsonObject();status.addProperty("available",false);status.addProperty("error","자료 목록을 확인하지 못했어요. 원본은 유지했어요.");out.add("library",status);}
                    JsonObject access=new JsonObject();access.addProperty("checkedAt",Instant.now().toString());
                    access.addProperty("writeSupported",true);access.addProperty("writeAuthorizedThisTurn",Arrays.asList(scope.split(",")).contains("planner"));
                    access.addProperty("scheduleBatchSupported",true);
                    try{State state=planner.load();access.addProperty("readAvailable",true);access.addProperty("revision",state.revision());}
                    catch(Exception failure){access.addProperty("readAvailable",false);access.addProperty("error","플래너 데이터를 읽지 못했어요. 원본은 보존했어요.");}
                    out.add("plannerAccess",access);
                    JsonObject memoryAccess=new JsonObject();memoryAccess.addProperty("readAvailable",true);memoryAccess.addProperty("writeSupported",true);memoryAccess.addProperty("writeAuthorizedThisTurn",Arrays.asList(scope.split(",")).contains("memory"));out.add("memoryAccess",memoryAccess);
                    try{JsonObject info=undoInfo();if(!info.isEmpty())info.addProperty("sameSession",info.has("context")&&session.equals(text(info.getAsJsonObject("context"),"session","",200)));out.add("undo",undoPreview(info));
                        boolean eligible=info.has("context")&&info.has("available")&&info.get("available").getAsBoolean()
                            &&session.equals(text(info.getAsJsonObject("context"),"session","",200))
                            &&System.currentTimeMillis()-info.get("at").getAsLong()<1_800_000;
                        out.addProperty("personalizationResetThisTurn",personalizationReset&&Arrays.asList(scope.split(",")).contains("memory"));
                        boolean libraryTurn=libraryContext!=null&&(libraryContext.has("pendingMove")||libraryContext.has("pendingClarification")||!library.scopes().isEmpty()||LIBRARY_ROUTING_HINT.matcher(question).find());
                        out.addProperty("recoveryInterpretationEligible",eligible&&!personalizationReset&&!recoveryInterpreted&&!mutated&&!(library!=null&&library.mutated())&&(!libraryTurn||"library".equals(text(info,"domain","",30))));
                        out.addProperty("recoveryDecision",recoveryDecision);
                    }catch(Exception unavailable){JsonObject info=new JsonObject();info.addProperty("available",false);info.addProperty("error","복원 기록을 읽지 못했어요.");out.add("undo",info);}
                    out.addProperty("semanticMutationAuthorization",true);out.add("mutationReferences",mutationAuthority.context());
                    out.addProperty("mutationScope",scope);out.addProperty("authorizationQuote",grant);yield out;
                }
                case "profile.get"->{keys(args,Set.of());yield profile.get();}
                case "memory.read"->{keys(args,Set.of());yield readMemory();}
                case "memory.update"->{authorize(request,"memory");yield updateMemory(args);}
                case "internal.recoveryIntent"->interpretRecovery(args);
                case "internal.mutationIntent"->interpretMutation(args);
                case "internal.libraryIntent"->{
                    if(library==null)throw new IllegalArgumentException("자료 관리 연결 상태를 확인해 주세요.");
                    if((recoveryLimit!=null||recoveryDecision.equals("clarify"))&&args.has("decision")&&!Set.of("none","reject").contains(args.get("decision").getAsString()))throw new LocalDenied("authorization_required","직전 작업 복원 요청을 다른 파일 변경 권한으로 넓힐 수 없어요.");
                    JsonObject intentResult=library.interpretIntent(args);
                    // File authorization has its own provenance so a mixed planner/
                    // library request cannot replace another domain's approved quote.
                    String other=Arrays.stream(scope.split(",")).filter(s->!s.isEmpty()&&!s.startsWith("library")).collect(java.util.stream.Collectors.joining(","));
                    String extra=library.scopes();scope=other.isEmpty()?extra:extra.isEmpty()?other:other+","+extra;
                    yield intentResult;
                }
                case "actions.undo"->{authorizeUndo(request);yield undo(args);}
                case "planner.query"->query(args);
                case "planner.apply"->{authorize(request,"planner");yield apply(args);}
                case "planner.scheduleBatch"->{authorize(request,"planner");yield scheduleBatch(args);}
                default->{if(library!=null&&AssistantLibraryActions.supports(tool)){
                    if(!Set.of("library.query","library.open").contains(tool)&&Arrays.asList(scope.split(",")).contains("undo")&&!undoWritten)throw new LocalDenied("undo_required","직전 작업을 되돌리는 요청을 다른 파일 변경으로 대신하지 않았어요.");
                    yield library.handle(tool,args,text(request,"authorizationQuote","",2000));}throw new IllegalArgumentException("허용되지 않은 로컬 도구예요.");}
            };
            reply.addProperty("ok",true);reply.add("data",result);
        }catch(Exception failure){if(failure instanceof IllegalArgumentException)mutationUncertain=uncertainBefore;reply.addProperty("ok",false);reply.addProperty("error",failure instanceof IllegalArgumentException?failure.getMessage():"로컬 데이터를 처리하지 못했어요. 원본은 보존했어요.");if(failure instanceof LocalDenied denied)reply.addProperty("code",denied.code);if(failure instanceof AssistantLibraryActions.Denied denied){reply.addProperty("code",denied.code);if(!denied.proposalId.isEmpty())reply.addProperty("proposalId",denied.proposalId);}}
        return reply;
    }
    synchronized String failureNotice(){
        if(mutationUncertain)return "저장 결과를 확인하지 못했어요. 같은 변경을 다시 요청하기 전에 저장 상태를 확인해 주세요.";
        if(plannerWritten||memoryWritten||undoWritten||library!=null&&library.mutated())return "저장된 변경은 유지돼요.";
        return "";
    }
    private void authorize(JsonObject request,String required){
        if(Arrays.asList(scope.split(",")).contains("undo")&&!undoWritten)throw new LocalDenied("undo_required","먼저 직전 작업을 되돌려야 해요. 실패한 복원을 다른 변경으로 우회할 수 없어요.");
        if(!Arrays.asList(scope.split(",")).contains(required)||!grant.equals(text(request,"authorizationQuote","",2000))){
            if(!cancelledTurn&&!question.isBlank()){
                JsonObject args=obj(request,"arguments");Set<String> operations=new HashSet<>();List<String> summary=new ArrayList<>();
                if(required.equals("planner")&&"planner.scheduleBatch".equals(text(request,"tool","",80))){
                    for(JsonElement e:array(args,"entries",AssistantPlannerBatch.MAX_ENTRIES))summary.add("일정 일괄 추가 — "+text(e.getAsJsonObject(),"title","일정",200));
                }else if(required.equals("planner"))for(JsonElement e:array(args,"changes",200)){
                    JsonObject c=e.getAsJsonObject();String operation=choice(c,"operation",Set.of("create","update","delete"));operations.add(operation);
                    String entity=choice(c,"entity",Set.of("event","task","weeklyTask","weeklyGoal","eventTag","todoTag"));JsonObject fields=obj(c,"fields");
                    String label=switch(entity){case "event"->"일정";case "task"->"일간 TODO";case "weeklyTask"->"주간 TODO";case "weeklyGoal"->"주간 목표";default->"태그";};
                    String verb=switch(operation){case "create"->"추가";case "delete"->"삭제";default->"수정";};
                    String detail=fields.entrySet().stream().map(f->fieldLabel(f.getKey())+": "+f.getValue().toString().replace("\"","")).collect(java.util.stream.Collectors.joining(", "));
                    summary.add(label+" "+verb+(detail.isEmpty()?"":" — "+detail));
                }else summary.add("개인화 메모리 변경: "+obj(args,"set"));
                if(!summary.isEmpty()){
                    throw new LocalDenied("confirmation_required",String.join("\n",summary)+"\n이 내용으로 진행해도 될까요? 동의하시면 이어서 처리할게요.");
                }
            }
            throw new LocalDenied("authorization_required","사용자가 직접 요청한 작업만 변경할 수 있어요.");
        }
    }
    private static JsonObject accountProfile(){
        JsonObject out=new JsonObject();out.add("name",JsonNull.INSTANCE);out.add("id",JsonNull.INSTANCE);out.addProperty("identityStatus","로컬 개발자 모드 · 로그인 계정 이름/아이디 미연결");
        out.addProperty("readOnly",true);out.addProperty("asOf",Instant.now().toString());
        try{CreditWallet.Snapshot s=CreditWallet.peek(PdfLibraryStore.defaultRoot());out.addProperty("credits",s.balance());out.addProperty("plan",s.activePlan());out.addProperty("planActive",s.hasActivePlan());out.addProperty("planExpiresAt",s.planExpiresAt()==null?null:s.planExpiresAt().toString());}
        catch(Exception e){out.add("credits",JsonNull.INSTANCE);out.add("plan",JsonNull.INSTANCE);out.addProperty("status","계정 사용량을 확인하지 못했어요.");}
        return out;
    }
    synchronized JsonObject preferencesSnapshot() throws Exception {return readMemory();}
    record PreferencesDebug(String path,boolean exists,String raw,JsonObject personalization,String error){}
    synchronized PreferencesDebug preferencesDebug() throws Exception {
        String path=memoryFile.toAbsolutePath().normalize().toString();
        if(!Files.exists(memoryFile))return new PreferencesDebug(path,false,"",readMemory(),"");
        if(Files.size(memoryFile)>4_000_000)throw new IllegalArgumentException("개인화 파일의 크기를 확인해 주세요.");
        String raw=Files.readString(memoryFile);
        try{return new PreferencesDebug(path,true,raw,parseMemory(raw),"");}
        catch(RuntimeException failure){return new PreferencesDebug(path,true,raw,null,"저장 파일이 개인화 데이터 형식 검사를 통과하지 못했어요.");}
    }
    private JsonObject readMemory() throws Exception {
        if(!Files.exists(memoryFile)){JsonObject out=new JsonObject();out.addProperty("revision",0);out.add("values",new JsonObject());return out;}
        if(Files.size(memoryFile)>4_000_000)throw new IllegalArgumentException("개인화 파일의 크기를 확인해 주세요.");
        return parseMemory(Files.readString(memoryFile));
    }
    private static JsonObject parseMemory(String raw){
        JsonObject doc=JsonParser.parseString(raw).getAsJsonObject();
        if(!"synesis-assistant-preferences".equals(str(doc,"format",80))||integer(doc,"version",1,1)!=1)throw new IllegalArgumentException("개인화 파일 형식을 확인해 주세요.");
        number(doc,"revision");validateValues(obj(doc,"values"));JsonObject out=new JsonObject();out.add("revision",doc.get("revision"));out.add("values",doc.get("values").deepCopy());return out;
    }
    private JsonObject updateMemory(JsonObject args) throws Exception {
        keys(args,Set.of("expectedRevision","set","remove"));long expected=number(args,"expectedRevision");JsonObject set=obj(args,"set");validateValues(set);
        JsonArray remove=array(args,"remove",MEMORY_KEYS.size());for(JsonElement e:remove)if(!e.isJsonPrimitive()||!MEMORY_KEYS.contains(e.getAsString()))throw new IllegalArgumentException("허용되지 않은 개인화 항목이에요.");
        if(set.isEmpty()&&remove.isEmpty())throw new IllegalArgumentException("변경할 개인화 항목이 없어요.");
        JsonObject semantic=args.deepCopy();semantic.remove("expectedRevision");String operation=hash(turn+"memory"+canonical(semantic));Files.createDirectories(memoryFile.getParent());
        synchronized(AssistantLocal.class){try(var channel=FileChannel.open(memoryFile.resolveSibling("user-preferences.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var ignored=channel.lock()){
            JsonObject current=readMemory(),doc=Files.exists(memoryFile)?JsonParser.parseString(Files.readString(memoryFile)).getAsJsonObject():new JsonObject();
            JsonObject receipts=doc.has("operations")?doc.getAsJsonObject("operations"):new JsonObject();
            if(receipts.has(operation)){mutated=true;memoryWritten=true;return current;}
            if(memoryWritten)throw new IllegalArgumentException("이번 요청의 개인화 변경은 이미 저장했어요. 추가 변경은 다음 메시지로 요청해 주세요.");
            if(number(current,"revision")!=expected)throw new IllegalArgumentException("개인화 메모리가 변경됐어요. 다시 읽은 뒤 수정해 주세요.");
            if(receipts.size()>=10000)throw new IllegalArgumentException("개인화 작업 기록이 가득 찼어요.");
            if(set.has("tone")&&!set.has("communicationStyle")&&!remove.contains(new JsonPrimitive("communicationStyle"))&&STYLE_NUANCE.matcher(question).find())
                throw new LocalDenied("memory_detail_required","사용자가 구체적인 대화 스타일을 요청했어요. tone 분류만 저장하지 말고, 요청의 뉘앙스와 조건을 communicationStyle에 함께 담아 다시 보내 주세요. 관련 없는 기존 선호는 유지해요.");
            if(recoveryLimit!=null&&recoveryLimit.has("keys")){
                Set<String> allowed=new HashSet<>();recoveryLimit.getAsJsonArray("keys").forEach(k->allowed.add(k.getAsString()));
                if(allowed.contains("tone")||allowed.contains("communicationStyle")){allowed.add("tone");allowed.add("communicationStyle");}
                if(!allowed.containsAll(set.keySet())||remove.asList().stream().anyMatch(k->!allowed.contains(k.getAsString())))throw new IllegalArgumentException("직전 작업에서 바꾼 개인화 항목만 정정할 수 있어요.");
            }
            JsonObject values=obj(current,"values").deepCopy();set.entrySet().forEach(e->values.add(e.getKey(),e.getValue().deepCopy()));remove.forEach(e->values.remove(e.getAsString()));validateValues(values);
            JsonObject undo=new JsonObject();JsonObject recovery=recoveryContext();JsonArray changedKeys=new JsonArray();set.keySet().forEach(changedKeys::add);remove.forEach(changedKeys::add);recovery.add("keys",changedKeys);undo.add("context",recovery);undo.addProperty("id",operation);undo.add("at",recovery.get("at"));undo.addProperty("revision",expected+1);undo.addProperty("undone",false);undo.add("before",obj(current,"values").deepCopy());doc.add("assistantUndo",undo);
            doc.addProperty("format","synesis-assistant-preferences");doc.addProperty("version",1);doc.addProperty("revision",expected+1);doc.add("values",values);receipts.addProperty(operation,expected+1);doc.add("operations",receipts);
            mutationUncertain=true;atomicWrite(memoryFile,doc);mutationUncertain=false;mutated=true;memoryWritten=true;return readMemory();
        }}
    }
    private static void validateValues(JsonObject values){
        keys(values,MEMORY_KEYS);
        for(String key:values.keySet())switch(key){
            case "preferredName"->str(values,key,80);
            case "language"->{if(!str(values,key,20).matches("[a-z]{2,3}(?:-[A-Za-z]{2,4})?"))throw new IllegalArgumentException("언어 코드를 확인해 주세요.");}
            case "tone"->choice(values,key,Set.of("polite","casual","formal"));
            case "communicationStyle"->str(values,key,2000);
            case "responseLength"->choice(values,key,Set.of("concise","balanced","detailed"));
            case "notes"->{int total=0;for(JsonElement e:array(values,key,32)){if(!e.isJsonPrimitive()||!e.getAsJsonPrimitive().isString()||e.getAsString().isBlank()||e.getAsString().length()>1000)throw new IllegalArgumentException("개인화 메모는 항목당 1,000자, 32개까지 저장해요.");total+=e.getAsString().length();}if(total>16000)throw new IllegalArgumentException("개인화 메모 전체는 16,000자까지 저장해요. 의미를 유지해 중복만 정리해 주세요.");}
        }
    }
    private JsonObject query(JsonObject args) throws Exception {
        keys(args,Set.of("from","to","kinds","offset","limit","expectedRevision"));LocalDate from=date(args,"from"),to=date(args,"to");
        if(!to.isAfter(from)||ChronoUnit.DAYS.between(from,to)>366)throw new IllegalArgumentException("조회 범위는 1~366일이에요. 종료일은 포함하지 않아요.");
        int offset=args.has("offset")?integer(args,"offset",0,1000000):0,limit=args.has("limit")?integer(args,"limit",1,100):60;
        Set<String> kinds=new HashSet<>(Set.of("event","task","weeklyTask","weeklyGoal","eventTag","todoTag"));
        if(args.has("kinds")){kinds.clear();for(JsonElement e:array(args,"kinds",6))kinds.add(e.getAsString());if(!Set.of("event","task","weeklyTask","weeklyGoal","eventTag","todoTag").containsAll(kinds))throw new IllegalArgumentException("조회 종류를 확인해 주세요.");}
        State s=planner.load();
        if((offset>0&&!args.has("expectedRevision"))||(args.has("expectedRevision")&&number(args,"expectedRevision")!=s.revision()))throw new IllegalArgumentException("페이지를 읽는 중 플래너 버전이 달라졌어요. 최신 revision으로 첫 페이지부터 다시 조회해 주세요.");
        if(observedRevision!=s.revision()){observed.clear();observedRevision=s.revision();}
        JsonArray rows=new JsonArray();
        if(kinds.contains("event"))for(Occurrence o:occurrences(s,from,to)){JsonObject row=row("event",o.event());row.addProperty("occurrenceStart",o.start().toString());row.addProperty("occurrenceEnd",o.end().toString());rows.add(row);}
        if(kinds.contains("task"))s.tasks().stream().filter(t->!t.date().isBefore(from)&&t.date().isBefore(to)).forEach(t->rows.add(row("task",t)));
        if(kinds.contains("weeklyTask"))s.weeklyTasks().stream().filter(t->t.week().isBefore(to)&&t.week().plusWeeks(1).isAfter(from)).forEach(t->rows.add(row("weeklyTask",t)));
        if(kinds.contains("weeklyGoal"))s.weeklyGoals().stream().filter(t->t.week().isBefore(to)&&t.week().plusWeeks(1).isAfter(from)).forEach(t->rows.add(row("weeklyGoal",t)));
        if(kinds.contains("eventTag"))s.tags().forEach(t->rows.add(row("eventTag",t)));
        if(kinds.contains("todoTag"))s.todoTags().forEach(t->rows.add(row("todoTag",t)));
        JsonArray page=new JsonArray();int bytes=0;
        for(int i=offset;i<rows.size()&&page.size()<limit;i++){
            JsonObject r=rows.get(i).getAsJsonObject();int size=JSON.toJson(r).getBytes(StandardCharsets.UTF_8).length;if(bytes+size>80000&&!page.isEmpty())break;bytes+=size;page.add(r);
            observed.computeIfAbsent(str(r,"entity",20),k->new HashSet<>()).add(str(r,"id",128));
        }
        JsonObject result=new JsonObject();result.addProperty("revision",s.revision());result.addProperty("from",from.toString());result.addProperty("to",to.toString());result.add("items",page);result.addProperty("total",rows.size());result.addProperty("hasMore",offset+page.size()<rows.size());result.addProperty("nextOffset",offset+page.size());return result;
    }
    private static JsonObject row(String entity,Object value){JsonObject r=JSON.toJsonTree(value).getAsJsonObject();r.addProperty("entity",entity);return r;}
    private JsonObject scheduleBatch(JsonObject args) throws Exception {
        keys(args,Set.of("expectedRevision","entries"));long expected=number(args,"expectedRevision");JsonArray entries=array(args,"entries",AssistantPlannerBatch.MAX_ENTRIES);
        authorizeChange("create");
        if(recoveryLimit!=null)throw new LocalDenied("authorization_required","일괄 등록을 되돌린 뒤 다시 등록하려면 원하는 반복 규칙을 새 요청으로 알려 주세요.");
        String op=hash(turn+"planner.scheduleBatch"+canonical(entries));
        if(plannerWritten&&!planner.hasAssistantOperation(op))throw new IllegalArgumentException("이번 메시지의 플래너 변경은 이미 저장했어요. 남은 모든 등록 규칙을 한 번의 일괄 등록에 담아 주세요.");
        AssistantPlannerBatch batch=new AssistantPlannerBatch(entries);
        mutationUncertain=true;
        JsonObject result=planner.applyAssistantBatch(op,expected,recoveryContext(),s->batch.apply(s,op));
        mutationUncertain=false;
        if(result.get("applied").getAsBoolean()){mutated=true;plannerWritten=true;observedRevision=-1;observed.clear();}
        return result;
    }
    private JsonObject apply(JsonObject args) throws Exception {
        keys(args,Set.of("expectedRevision","changes"));long expected=number(args,"expectedRevision");JsonArray changes=array(args,"changes",200);
        String op=hash(turn+"planner"+canonical(changes));
        if(changes.isEmpty())throw new IllegalArgumentException("변경할 항목이 없어요.");
        if(planner.hasAssistantOperation(op)){mutated=true;plannerWritten=true;JsonObject out=new JsonObject();out.addProperty("revision",planner.load().revision());out.addProperty("applied",true);out.addProperty("replayed",true);out.add("changes",changes.deepCopy());return out;}
        if(plannerWritten)throw new IllegalArgumentException("이번 요청의 플래너 변경은 이미 저장했어요. 추가 변경은 다음 메시지로 요청해 주세요.");
        checkRecoveryChanges(changes);
        long checkedRevision=observedRevision<0?queryNewDailyTaskRevision(changes):observedRevision;
        if(checkedRevision<0||expected!=checkedRevision)throw new IllegalArgumentException("먼저 수정 대상 기간과 태그를 조회해 주세요.");
        JsonObject recovery=recoveryContext();JsonArray recoveryChanges=changes.deepCopy();int recoveryIndex=0;
        for(JsonElement element:recoveryChanges){JsonObject c=element.getAsJsonObject();if("create".equals(c.get("operation").getAsString()))c.addProperty("id",UUID.nameUUIDFromBytes((op+":"+recoveryIndex).getBytes(StandardCharsets.UTF_8)).toString());recoveryIndex++;}
        recovery.add("changes",recoveryChanges);
        State result=planner.applyAssistant(op,expected,recovery,s->{
            List<Event> events=new ArrayList<>(s.events());List<Task> tasks=new ArrayList<>(s.tasks());List<WeeklyTask> weekly=new ArrayList<>(s.weeklyTasks());List<WeeklyGoal> goals=new ArrayList<>(s.weeklyGoals());List<Tag> tags=new ArrayList<>(s.tags()),todoTags=new ArrayList<>(s.todoTags());
            Set<String> touched=new HashSet<>();int index=0;
            for(JsonElement element:changes){JsonObject c=element.getAsJsonObject();keys(c,Set.of("entity","operation","id","fields"));String entity=str(c,"entity",20),action=choice(c,"operation",Set.of("create","update","delete"));JsonObject f=obj(c,"fields");
                authorizeChange(action);
                if(action.equals("create")&&c.has("id")&&!c.get("id").isJsonNull())throw new IllegalArgumentException("새 항목의 식별자는 앱에서 정해요.");
                if(!action.equals("delete")&&f.isEmpty())throw new IllegalArgumentException("변경할 내용을 확인해 주세요.");
                String id=action.equals("create")?UUID.nameUUIDFromBytes((op+":"+index).getBytes(StandardCharsets.UTF_8)).toString():str(c,"id",128);index++;
                if(!action.equals("create")&&!observed.getOrDefault(entity,Set.of()).contains(id))throw new IllegalArgumentException("조회한 항목만 수정할 수 있어요. 대상을 다시 확인해 주세요.");
                if(!touched.add(entity+id))throw new IllegalArgumentException("한 작업에서 같은 항목을 두 번 바꿀 수 없어요.");
                boolean delete=action.equals("delete");if(delete&&!f.isEmpty())throw new IllegalArgumentException("삭제 요청에는 변경 필드를 넣지 않아요.");
                switch(entity){
                    case "event"->{keys(f,Set.of("title","description","start","end","allDay","color","tags","important","repeat"));Event old=events.stream().filter(e->e.id().equals(id)).findFirst().orElse(null);requireExisting(action,old);
                        if(old!=null&&old.repeat()!=Repeat.NONE)authorizeSeries();
                        if(delete){events.remove(old);break;}
                        Event next=new Event(id,text(f,"title",old==null?null:old.title(),200),text(f,"description",old==null?"":old.description(),10000),f.has("start")?LocalDateTime.parse(str(f,"start",40)):old==null?missing("시작 시간"):old.start(),f.has("end")?LocalDateTime.parse(str(f,"end",40)):old==null?missing("종료 시간"):old.end(),bool(f,"allDay",old!=null&&old.allDay()),(f.has("color")?EventColor.valueOf(text(f,"color",null,20)):old!=null?old.color():EventColor.values()[java.util.concurrent.ThreadLocalRandom.current().nextInt(EventColor.values().length)]),f.has("tags")?resolveTags(f,tags,op):old==null?List.of():old.tagIds(),bool(f,"important",old!=null&&old.important()),Repeat.valueOf(text(f,"repeat",old==null?"NONE":old.repeat().name(),20)),old==null?-1:old.reminderMinutes());events.remove(old);events.add(next);}
                    case "task"->{keys(f,Set.of("title","detail","date","completed"));Task old=tasks.stream().filter(t->t.id().equals(id)).findFirst().orElse(null);requireExisting(action,old);if(delete){tasks.remove(old);break;}Task next=new Task(id,text(f,"title",old==null?null:old.title(),200),f.has("date")?date(f,"date"):old==null?missing("날짜"):old.date(),text(f,"detail",old==null?"":old.detail(),1000),bool(f,"completed",old!=null&&old.completed()));tasks.remove(old);tasks.add(next);}
                    case "weeklyTask"->{keys(f,Set.of("title","deadline","week","tags","completed"));WeeklyTask old=weekly.stream().filter(t->t.id().equals(id)).findFirst().orElse(null);requireExisting(action,old);if(delete){weekly.remove(old);break;}WeeklyTask next=new WeeklyTask(id,text(f,"title",old==null?null:old.title(),200),f.has("deadline")?(f.get("deadline").isJsonNull()?null:date(f,"deadline")):old==null?null:old.deadline(),f.has("week")?date(f,"week"):old==null?missing("주 시작일"):old.week(),f.has("tags")?resolveTags(f,todoTags,op):old==null?List.of():old.tagIds(),bool(f,"completed",old!=null&&old.completed()));weekly.remove(old);weekly.add(next);}
                    case "weeklyGoal"->{keys(f,Set.of("title","week","target","completed"));WeeklyGoal old=goals.stream().filter(t->t.id().equals(id)).findFirst().orElse(null);requireExisting(action,old);if(delete){goals.remove(old);break;}WeeklyGoal next=new WeeklyGoal(id,text(f,"title",old==null?null:old.title(),200),f.has("week")?date(f,"week"):old==null?missing("주 시작일"):old.week(),f.has("target")?integer(f,"target",1,100000):old==null?missing("목표 횟수"):old.target(),f.has("completed")?integer(f,"completed",0,100000):old==null?0:old.completed());goals.remove(old);goals.add(next);}
                    case "eventTag","todoTag"->{keys(f,Set.of("name"));List<Tag> list=entity.equals("eventTag")?tags:todoTags;Tag old=list.stream().filter(t->t.id().equals(id)).findFirst().orElse(null);requireExisting(action,old);if(delete){list.remove(old);if(entity.equals("eventTag"))events.replaceAll(e->e.withTags(e.tagIds().stream().filter(t->!t.equals(id)).toList()));else weekly.replaceAll(t->t.withTags(t.tagIds().stream().filter(tag->!tag.equals(id)).toList()));}else{Tag next=new Tag(id,text(f,"name",old==null?null:old.name(),30));list.remove(old);list.add(next);}}
                    default->throw new IllegalArgumentException("허용되지 않은 플래너 항목이에요.");
                }
            }
            mutationUncertain=true;
            return new State(s.revision(),events,tags,tasks,s.goals(),s.notificationsEnabled(),s.deliveredReminders(),weekly,todoTags,goals,s.monthlyTasks().stream().map(t->t.withTags(t.tagIds().stream().filter(tag->todoTags.stream().anyMatch(v->v.id().equals(tag))).toList())).toList());
        });
        mutationUncertain=false;mutated=true;plannerWritten=true;observedRevision=-1;observed.clear();JsonObject out=new JsonObject();out.addProperty("revision",result.revision());out.addProperty("applied",true);out.add("changes",changes.deepCopy());return out;
    }
    private long queryNewDailyTaskRevision(JsonArray changes)throws Exception{
        LocalDate first=null,last=null;
        for(JsonElement entry:changes){
            JsonObject change=entry.getAsJsonObject();
            if(!"task".equals(text(change,"entity","",20))||!"create".equals(text(change,"operation","",10))
                    ||change.has("id")&&!change.get("id").isJsonNull())return -1;
            LocalDate day=date(obj(change,"fields"),"date");
            if(first==null||day.isBefore(first))first=day;
            if(last==null||day.isAfter(last))last=day;
        }
        if(first==null||ChronoUnit.DAYS.between(first,last)>=366)return -1;
        // The query supplies the observed revision. The original expected
        // revision still has to match both this observation and the commit.
        JsonObject args=new JsonObject();
        args.addProperty("from",first.toString());
        args.addProperty("to",last.plusDays(1).toString());
        JsonArray kinds=new JsonArray();kinds.add("task");args.add("kinds",kinds);
        args.addProperty("limit",1);
        long revision=query(args).get("revision").getAsLong();
        // This internal read does not give a later update/delete any observed IDs.
        observed.clear();
        observedRevision=-1;
        return revision;
    }
    private JsonObject interpretMutation(JsonObject args){
        if(recoveryLimit!=null||recoveryDecision.equals("clarify"))throw new LocalDenied("authorization_required","직전 작업 정정의 범위를 새 변경 권한으로 넓힐 수 없어요.");
        AssistantMutationAuthority.Decision intent=mutationAuthority.interpret(args);
        String other=Arrays.stream(scope.split(",")).filter(v->!v.isEmpty()&&!Set.of("planner","memory","undo").contains(v)).collect(java.util.stream.Collectors.joining(","));
        List<String> scopes=new ArrayList<>();if(!other.isEmpty())scopes.add(other);scopes.addAll(new TreeSet<>(intent.scopes()));scope=String.join(",",scopes);
        grant=intent.quote();approvedOperations=intent.operations();
        personalizationReset=intent.reset();seriesConfirmed=intent.series();cancelledTurn=intent.kind().equals("reject")||intent.kind().equals("none");
        JsonObject out=new JsonObject();out.addProperty("decision",intent.kind());return out;
    }
    private JsonObject recoveryContext(){
        JsonObject out=new JsonObject();out.addProperty("session",session);out.addProperty("turn",turn);out.addProperty("request",grant);out.addProperty("allRecurring",seriesConfirmed);
        try{JsonObject latest=undoInfo();out.addProperty("at",Math.max(System.currentTimeMillis(),latest.has("at")?latest.get("at").getAsLong()+1:0));}catch(Exception failure){throw new IllegalStateException("직전 작업 기록을 확인하지 못해 새 변경을 저장하지 않았어요.",failure);}return out;
    }
    /** Internal interpreter result, never a tool exposed in the model's action catalog. */
    private JsonObject interpretRecovery(JsonObject args) throws Exception {
        keys(args,Set.of("id","intent","clear","evidence","question"));
        if(recoveryInterpreted||mutated||library!=null&&library.mutated())throw new IllegalArgumentException("이번 요청의 맥락 판단은 이미 끝났어요.");
        if(!question.equals(str(args,"question",2000)))throw new IllegalArgumentException("현재 사용자 요청과 판단 근거가 달라요.");
        JsonObject latest=undoInfo();String target=str(args,"id",64);
        if(latest.isEmpty()||!latest.has("id")||!latest.get("id").getAsString().equals(target)||!latest.get("available").getAsBoolean()||!latest.has("context"))throw new IllegalArgumentException("직전 작업의 맥락을 확인하지 못했어요.");
        JsonObject previous=latest.getAsJsonObject("context");
        if(!session.equals(text(previous,"session","",200))||System.currentTimeMillis()-latest.get("at").getAsLong()>=1_800_000)throw new IllegalArgumentException("다른 대화 또는 오래된 작업의 권한은 이어받지 않아요.");
        String intent=choice(args,"intent",Set.of("none","undo","redo","revise"));boolean clear=bool(args,"clear",false);
        String evidence=text(args,"evidence","",2000);
        String direct=question.replaceAll("(?s)```.*?```","").replaceAll("(?m)^\\s*>.*$","").replaceAll("`[^`]*`|\"[^\"]*\"|'[^']*'|“[^”]*”|‘[^’]*’","");
        if(!intent.equals("none")&&(evidence.isBlank()||!direct.contains(evidence)))throw new IllegalArgumentException("직접 입력한 요청의 근거가 없어요.");
        recoveryInterpreted=true;recoveryDecision=intent;
        // A semantic refusal/ambiguity also removes a keyword-based false positive.
        scope=Arrays.stream(scope.split(",")).filter(v->!v.equals("undo")).collect(java.util.stream.Collectors.joining(","));
        if(!intent.equals("none")){
            if(!clear){scope="";grant="";recoveryDecision="clarify";}
            else{
                String domain=latest.get("domain").getAsString();
                if(domain.equals("library")&&!intent.equals("undo"))throw new LocalDenied("authorization_required","직전 파일 작업을 먼저 되돌리거나, 새로 원하는 파일 작업을 구체적으로 알려 주세요.");
                scope=intent.equals("undo")?"undo":intent.equals("redo")?"undo,"+domain:domain;
                grant=intent.equals("undo")?question:text(previous,"request","",2000)+"\n현재 사용자의 정정: "+question;
                if(grant.length()>2000)throw new IllegalArgumentException("정정 요청이 너무 길어요. 작업 범위를 나눠 주세요.");
                cancelledTurn=false;recoveryLimit=previous.deepCopy();seriesConfirmed=bool(previous,"allRecurring",false);
                if(domain.equals("planner")){
                    Set<String> ops=new HashSet<>();previous.getAsJsonArray("changes").forEach(c->ops.add(c.getAsJsonObject().get("operation").getAsString()));
                    approvedOperations=intent.equals("revise")?Set.of("update"):Set.copyOf(ops);
                }
            }
        }
        JsonObject out=new JsonObject();out.addProperty("intent",recoveryDecision);return out;
    }
    private void checkRecoveryChanges(JsonArray changes){
        if(recoveryLimit==null||!recoveryLimit.has("changes"))return;
        JsonArray original=recoveryLimit.getAsJsonArray("changes");
        if(changes.size()>original.size())throw new IllegalArgumentException("직전 작업의 범위를 넘는 재작업은 별도 요청해 주세요.");
        for(JsonElement element:changes){
            JsonObject next=element.getAsJsonObject();boolean allowed=false;
            for(JsonElement old:original){JsonObject prior=old.getAsJsonObject();
                if(!text(next,"entity","",20).equals(text(prior,"entity","",20)))continue;
                if(recoveryDecision.equals("redo")&&text(prior,"operation","",20).equals("create")&&text(next,"operation","",20).equals("create")){allowed=true;break;}
                String priorId=text(prior,"id","",128);
                if(!priorId.isEmpty()&&priorId.equals(text(next,"id","",128))&&
                    (recoveryDecision.equals("revise")?text(next,"operation","",20).equals("update"):text(prior,"operation","",20).equals(text(next,"operation","",20)))){allowed=true;break;}
            }
            if(!allowed)throw new IllegalArgumentException("직전 작업과 관계없는 항목은 재작업 권한으로 바꿀 수 없어요.");
        }
    }
    private void authorizeUndo(JsonObject request){
        if(!Arrays.asList(scope.split(",")).contains("undo")||!grant.equals(text(request,"authorizationQuote","",2000)))
            throw new LocalDenied("authorization_required","되돌리기는 사용자가 직접 요청할 때만 실행해요.");
    }
    private JsonObject undoInfo() throws Exception {
        JsonObject latest=planner.assistantUndoInfo();if(!latest.isEmpty())latest.addProperty("domain","planner");
        if(Files.exists(memoryFile)){
            readMemory();JsonObject doc=JsonParser.parseString(Files.readString(memoryFile)).getAsJsonObject();
            if(doc.has("assistantUndo")){
                JsonObject record=doc.getAsJsonObject("assistantUndo");
                if(latest.isEmpty()||record.get("at").getAsLong()>latest.get("at").getAsLong()){
                    latest=record.deepCopy();latest.remove("before");latest.addProperty("domain","memory");
                    latest.addProperty("available",!record.get("undone").getAsBoolean()&&doc.get("revision").getAsLong()==record.get("revision").getAsLong());
                }
            }
        }
        if(library!=null){JsonObject info=library.undoInfo();if(!info.isEmpty()&&(latest.isEmpty()||info.get("at").getAsLong()>=latest.get("at").getAsLong())){latest=info;latest.addProperty("domain","library");}}
        return latest;
    }
    /** Full recovery IDs remain on disk/native; a thousand rows must not overflow the chat RPC. */
    private static JsonObject undoPreview(JsonObject info){
        JsonObject preview=info.deepCopy();
        if(preview.has("context")){
            JsonObject context=preview.getAsJsonObject("context");
            if(context.has("bulkSchedule")&&context.get("bulkSchedule").getAsBoolean()&&context.has("changes")){
                JsonArray all=context.getAsJsonArray("changes");context.addProperty("changeCount",all.size());
                if(all.size()>12){JsonArray sample=new JsonArray();for(int i=0;i<12;i++)sample.add(all.get(i));context.add("changes",sample);context.addProperty("changesTruncated",true);}
            }
        }
        return preview;
    }
    private JsonObject undo(JsonObject args) throws Exception {
        keys(args,Set.of("id"));String target=str(args,"id",64),operation=hash(turn+"undo"+target);
        JsonObject latest=undoInfo();
        if(latest.isEmpty()||!latest.has("id")||!target.equals(latest.get("id").getAsString()))throw new IllegalArgumentException("직전 저장 작업의 복원 기록이 없어요. 패치 이전 작업은 자동 복원할 수 없어요.");
        String domain=latest.get("domain").getAsString();
        // Retry of the same undo is successful without consuming an older operation.
        if(domain.equals("planner")&&planner.hasAssistantOperation(operation))return undoResult(domain,true);
        if(domain.equals("library")&&library.hasOperation(operation))return undoResult(domain,true);
        if(domain.equals("memory")&&Files.exists(memoryFile)){
            JsonObject doc=JsonParser.parseString(Files.readString(memoryFile)).getAsJsonObject();
            if(doc.has("operations")&&doc.getAsJsonObject("operations").has(operation))return undoResult(domain,true);
        }
        if(undoWritten||plannerWritten||memoryWritten||library!=null&&library.mutated())throw new IllegalArgumentException("되돌리기는 이번 메시지의 다른 저장보다 먼저 한 번만 실행해요.");
        if(!latest.get("available").getAsBoolean())throw new IllegalArgumentException("이미 되돌렸거나 작업 이후 데이터가 변경됐어요. 현재 데이터를 보존했어요.");
        if(!latest.has("context")||!session.equals(text(latest.getAsJsonObject("context"),"session","",200)))throw new IllegalArgumentException("현재 대화의 직전 작업만 되돌릴 수 있어요.");
        if(domain.equals("library")){
            mutationUncertain=true;JsonObject result=library.undo(operation,target);mutationUncertain=false;undoWritten=true;mutated=true;return result;
        }else if(domain.equals("planner")){
            mutationUncertain=true;planner.undoAssistant(operation,target,latest.get("revision").getAsLong());mutationUncertain=false;
        }else synchronized(AssistantLocal.class){
            try(var channel=FileChannel.open(memoryFile.resolveSibling("user-preferences.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);var ignored=channel.lock()){
                JsonObject doc=JsonParser.parseString(Files.readString(memoryFile)).getAsJsonObject(),record=doc.getAsJsonObject("assistantUndo");
                if(record==null||!target.equals(record.get("id").getAsString())||record.get("undone").getAsBoolean()||number(doc,"revision")!=number(record,"revision"))
                    throw new IllegalArgumentException("개인화 지침이 변경돼 되돌리지 않았어요.");
                JsonObject values=obj(record,"before");validateValues(values);long revision=number(doc,"revision")+1;
                JsonObject receipts=doc.getAsJsonObject("operations");if(receipts.size()>=10000)throw new IllegalArgumentException("개인화 작업 기록이 가득 찼어요.");
                doc.add("values",values.deepCopy());doc.addProperty("revision",revision);record.addProperty("undone",true);receipts.addProperty(operation,revision);
                mutationUncertain=true;atomicWrite(memoryFile,doc);mutationUncertain=false;
            }
        }
        undoWritten=true;mutated=true;observedRevision=-1;observed.clear();
        return undoResult(domain,false);
    }
    private JsonObject undoResult(String domain,boolean replayed){
        undoWritten=true;mutated=true;JsonObject out=new JsonObject();out.addProperty("undone",true);out.addProperty("domain",domain);out.addProperty("replayed",replayed);return out;
    }
    private static String fieldLabel(String key){return switch(key){case "title","name"->"이름";case "start"->"시작";case "end"->"종료";case "description","detail"->"설명";case "date"->"날짜";case "week"->"소속 주";case "deadline"->"마감일";case "tags"->"태그";case "target"->"목표 횟수";case "completed"->"완료";case "repeat"->"반복";case "important"->"다가오는 일정 표시";case "color"->"색";case "allDay"->"종일";default->"설정";};}
    private static void requireExisting(String action,Object old){if(!action.equals("create")&&old==null)throw new IllegalArgumentException("대상이 삭제됐어요. 다시 조회해 주세요.");}
    private void authorizeChange(String action){
        if(!approvedOperations.contains(action))throw new LocalDenied("operation_not_authorized","확인한 요청과 다른 종류의 변경이에요. 원하는 작업을 확인해 주세요.");
    }
    private void authorizeSeries(){
        if(!seriesConfirmed)throw new LocalDenied("series_confirmation_required","이 작업은 전체 반복 일정에 적용돼요. 전체 시리즈를 변경할지 확인해 주세요. 단일 회차 편집은 지원하지 않아요.");
    }
    static List<String> resolveTags(JsonObject f,List<Tag> tags,String op){List<String> ids=new ArrayList<>();for(JsonElement e:array(f,"tags",12)){
        if(!e.isJsonPrimitive()||!e.getAsJsonPrimitive().isString())throw new IllegalArgumentException("태그 이름을 확인해 주세요.");String name=e.getAsString().strip();new Tag("check",name);
        Tag tag=tags.stream().filter(t->t.name().equalsIgnoreCase(name)).findFirst().orElse(null);if(tag==null){tag=new Tag(UUID.nameUUIDFromBytes((op+name).getBytes(StandardCharsets.UTF_8)).toString(),name);tags.add(tag);}ids.add(tag.id());}return ids;}
    private static void atomicWrite(Path path,JsonObject value)throws Exception {Path tmp=Files.createTempFile(path.getParent(),"assistant-",".tmp");try{Files.writeString(tmp,JSON.toJson(value));try(var out=FileChannel.open(tmp,StandardOpenOption.WRITE)){out.force(true);}try{Files.move(tmp,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}catch(AtomicMoveNotSupportedException e){Files.move(tmp,path,StandardCopyOption.REPLACE_EXISTING);}}finally{Files.deleteIfExists(tmp);}}
    private static String canonical(JsonElement e){if(e.isJsonObject()){JsonObject o=new JsonObject();new TreeSet<>(e.getAsJsonObject().keySet()).forEach(k->o.add(k,JsonParser.parseString(canonical(e.getAsJsonObject().get(k)))));return JSON.toJson(o);}if(e.isJsonArray()){JsonArray a=new JsonArray();e.getAsJsonArray().forEach(v->a.add(JsonParser.parseString(canonical(v))));return JSON.toJson(a);}return JSON.toJson(e);}
    private static String hash(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
    private static void keys(JsonObject o,Set<String> allowed){if(!allowed.containsAll(o.keySet()))throw new IllegalArgumentException("허용되지 않은 필드가 있어요.");}
    private static JsonObject obj(JsonObject o,String k){if(!o.has(k)||!o.get(k).isJsonObject())throw new IllegalArgumentException(k+" 객체를 확인해 주세요.");return o.getAsJsonObject(k);}
    private static JsonArray array(JsonObject o,String k,int max){if(!o.has(k)||!o.get(k).isJsonArray()||o.getAsJsonArray(k).size()>max)throw new IllegalArgumentException(k+" 목록을 확인해 주세요.");return o.getAsJsonArray(k);}
    private static String str(JsonObject o,String k,int max){if(!o.has(k)||!o.get(k).isJsonPrimitive()||!o.getAsJsonPrimitive(k).isString()||o.get(k).getAsString().isBlank()||o.get(k).getAsString().length()>max)throw new IllegalArgumentException(k+" 값을 확인해 주세요.");return o.get(k).getAsString();}
    private static String text(JsonObject o,String k,String fallback,int max){if(!o.has(k)){if(fallback==null)return missing(k);return fallback;}if(!o.get(k).isJsonPrimitive()||!o.getAsJsonPrimitive(k).isString()||o.get(k).getAsString().length()>max)throw new IllegalArgumentException(k+" 값을 확인해 주세요.");return o.get(k).getAsString();}
    private static long number(JsonObject o,String k){try{if(!o.get(k).isJsonPrimitive()||!o.getAsJsonPrimitive(k).isNumber())throw new ArithmeticException();long n=o.get(k).getAsBigDecimal().longValueExact();if(n<0)throw new ArithmeticException();return n;}catch(Exception e){throw new IllegalArgumentException(k+" 정수를 확인해 주세요.");}}
    private static int integer(JsonObject o,String k,int min,int max){long n=number(o,k);if(n<min||n>max)throw new IllegalArgumentException(k+" 범위를 확인해 주세요.");return (int)n;}
    private static boolean bool(JsonObject o,String k,boolean fallback){if(!o.has(k))return fallback;if(!o.get(k).isJsonPrimitive()||!o.getAsJsonPrimitive(k).isBoolean())throw new IllegalArgumentException(k+" 논리값을 확인해 주세요.");return o.get(k).getAsBoolean();}
    private static String choice(JsonObject o,String k,Set<String> values){String value=str(o,k,40);if(!values.contains(value))throw new IllegalArgumentException(k+" 종류를 확인해 주세요.");return value;}
    private static LocalDate date(JsonObject o,String k){LocalDate d=LocalDate.parse(str(o,k,10));if(d.getYear()<1900||d.getYear()>2200)throw new IllegalArgumentException("날짜 범위를 확인해 주세요.");return d;}
    private static <T>T missing(String name){throw new IllegalArgumentException(name+" 정보가 필요해요. 사용자에게 물어봐 주세요.");}
}
