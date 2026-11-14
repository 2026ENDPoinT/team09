package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** The model interprets intent; this boundary binds it to this human turn and bounded native capabilities. */
final class AssistantMutationAuthority {
    record Decision(String kind,Set<String> scopes,Set<String> operations,String quote,boolean reset,boolean series){}
    private record Reference(String id,String question,long at,Boolean completed){}
    private final LinkedHashMap<String,Reference> references=new LinkedHashMap<>();
    private final Set<String> closed=new HashSet<>();
    private String session="",question="",accepted="";
    private long started;
    private Boolean completed;
    private Decision decision;
    private Reference pending;
    private Set<String> pendingScopes=Set.of(),pendingOperations=Set.of();
    private String pendingAnswer="";
    private String confirmationQuestion="";
    private boolean relatedDiscussion;
    private static final long MAX_AGE=1_800_000;

    void begin(String sessionId,String turnId,String text,JsonArray history){
        long now=System.currentTimeMillis();
        if(!session.equals(sessionId)){references.clear();clearPending();closed.clear();}
        else if(!question.isBlank())remember(question,started,completed);
        session=sessionId;question=text;started=now;accepted="";decision=null;completed=null;relatedDiscussion=false;
        if(history!=null)for(JsonElement raw:history){
            if(!raw.isJsonObject())continue;JsonObject row=raw.getAsJsonObject();
            try{
                if(row.has("question")&&row.get("question").isJsonPrimitive()&&row.getAsJsonPrimitive("question").isString()){
                    long at=row.has("timestampMs")?row.get("timestampMs").getAsLong():0;
                    String q=row.get("question").getAsString();
                    if(at>0&&now-at<MAX_AGE&&at<=now+60_000&&references.values().stream().noneMatch(ref->ref.question().equals(q)))remember(q,at,null);
                }
            }catch(RuntimeException ignored){}
        }
        references.values().removeIf(ref->now-ref.at()>MAX_AGE&&(pending==null||!ref.id().equals(pending.id())));
        while(references.size()>6)references.remove(references.values().stream().filter(ref->pending==null||!ref.id().equals(pending.id())).min(Comparator.comparingLong(Reference::at)).orElseThrow().id());
        closed.retainAll(references.keySet());
    }
    void finish(boolean changed){finish(changed,"");}
    void finish(boolean changed,String answer){
        completed=changed?Boolean.TRUE:null;
        if(changed)clearPending();
        else if(pending!=null&&relatedDiscussion){
            pendingAnswer=answer.substring(0,Math.min(1200,answer.length()));
            if(decision!=null&&decision.kind().equals("clarify"))confirmationQuestion=pendingAnswer;
        }
    }
    private void clearPending(){if(pending!=null)closed.add(pending.id());pending=null;pendingScopes=Set.of();pendingOperations=Set.of();pendingAnswer="";confirmationQuestion="";}
    private void remember(String text,long at,Boolean changed){
        if(text.isBlank()||text.length()>2000||at<=0)return;
        String id=hash(session+"\n"+at+"\n"+text);references.put(id,new Reference(id,text,at,changed));
    }
    JsonArray context(){
        JsonArray out=new JsonArray();List<Reference> rows=new ArrayList<>(references.values());rows.sort(Comparator.comparingLong(Reference::at));
        if(pending!=null)rows.removeIf(ref->ref.question().equals(pending.question())&&!ref.id().equals(pending.id()));
        Set<String> seen=new HashSet<>();List<Reference> latest=new ArrayList<>();
        for(int i=rows.size()-1;i>=0&&latest.size()<3;i--)if(seen.add(rows.get(i).question()))latest.add(rows.get(i));
        if(pending!=null&&latest.stream().noneMatch(ref->ref.id().equals(pending.id())))latest.add(pending);
        latest.sort(Comparator.comparingLong(Reference::at));for(Reference ref:latest){
            JsonObject row=new JsonObject();row.addProperty("id",ref.id());row.addProperty("question",ref.question().substring(0,Math.min(240,ref.question().length())));
            if(pending!=null&&pending.id().equals(ref.id())){
                row.addProperty("pending",true);row.addProperty("lastAnswer",pendingAnswer);
                row.addProperty("question",ref.question());row.addProperty("confirmationQuestion",confirmationQuestion);
                JsonArray scopes=new JsonArray();pendingScopes.stream().sorted().forEach(scopes::add);row.add("scopes",scopes);
                JsonArray ops=new JsonArray();pendingOperations.stream().sorted().forEach(ops::add);row.add("plannerOperations",ops);
            }
            if(Boolean.TRUE.equals(ref.completed()))row.addProperty("completed",true);out.add(row);
            if(closed.contains(ref.id()))row.addProperty("closed",true);
        }
        return out;
    }
    Decision interpret(JsonObject args){
        if(!args.keySet().equals(Set.of("question","decision","evidence","scopes","plannerOperations","referenceId","resetPersonalization","allRecurring")))throw new IllegalArgumentException("변경 의도 규격을 확인해 주세요.");
        String current=text(args,"question",2000),kind=text(args,"decision",20),evidence=text(args,"evidence",2000),referenceId=text(args,"referenceId",80);
        if(!current.equals(question))throw new IllegalArgumentException("현재 직접 입력한 요청과 변경 의도가 달라요.");
        if(!Set.of("request","approve","clarify","none","reject").contains(kind))throw new IllegalArgumentException("변경 의도 판단 값을 확인해 주세요.");
        Set<String> scopes=values(args,"scopes",Set.of("planner","memory"));
        Set<String> operations=values(args,"plannerOperations",Set.of("create","update","delete"));
        boolean reset=flag(args,"resetPersonalization"),series=flag(args,"allRecurring");
        boolean actionable=kind.equals("request")||kind.equals("approve");
        if(actionable&&(scopes.isEmpty()||scopes.contains("planner")&&operations.isEmpty()))throw new IllegalArgumentException("실행할 변경의 영역과 종류를 확인해 주세요.");
        if(!scopes.contains("planner")&&(!operations.isEmpty()||series)||!scopes.contains("memory")&&reset)throw new IllegalArgumentException("요청한 변경 영역을 벗어난 권한이에요.");
        if(Set.of("none","reject").contains(kind)&&(!scopes.isEmpty()||!operations.isEmpty()||reset||series))throw new IllegalArgumentException("조회·거절에는 변경 권한을 부여하지 않아요.");
        String direct=plain(evidence).strip();
        if((actionable||kind.equals("clarify"))&&(direct.isEmpty()||!question.contains(evidence)||!plain(question).contains(direct)))throw new IllegalArgumentException("인용·첨부가 아닌 현재 직접 요청의 근거를 확인해 주세요.");
        Reference ref=referenceId.isEmpty()?null:references.get(referenceId);
        if(!referenceId.isEmpty()&&(ref==null||System.currentTimeMillis()-ref.at()>MAX_AGE&&(pending==null||!pending.id().equals(ref.id()))))throw new IllegalArgumentException("이어지는 원래 요청을 확인하지 못했어요. 작업 내용을 알려 주세요.");
        if(kind.equals("approve")&&ref==null)throw new IllegalArgumentException("어떤 작업에 동의하셨는지 확인해 주세요.");
        if(kind.equals("approve")&&Boolean.TRUE.equals(ref.completed()))throw new IllegalArgumentException("이미 완료한 작업은 다시 실행하지 않았어요. 새 변경을 원하시면 내용을 알려 주세요.");
        if(kind.equals("approve")&&closed.contains(ref.id()))throw new IllegalArgumentException("이미 종료한 대기 작업은 다시 실행하지 않았어요. 새 변경을 원하시면 내용을 알려 주세요.");
        boolean continues=ref!=null&&pending!=null&&ref.id().equals(pending.id());
        if(continues&&(actionable||kind.equals("clarify"))&&(!pendingScopes.containsAll(scopes)||!pendingOperations.containsAll(operations)))throw new IllegalArgumentException("미완료 요청에서 맡긴 영역과 작업 종류만 이어서 처리할 수 있어요.");
        String quote=ref==null?question:ref.question()+"\n현재 직접 요청: "+question;
        if(quote.length()>2000)throw new IllegalArgumentException("이어지는 요청이 길어요. 변경할 내용을 한 번에 정리해 주세요.");
        String canonical=args.toString();
        if(!accepted.isEmpty()){
            if(!accepted.equals(canonical))throw new IllegalArgumentException("이 턴에서 확인한 변경 범위를 넓힐 수 없어요.");
            return decision;
        }
        accepted=canonical;decision=new Decision(kind,actionable?Set.copyOf(scopes):Set.of(),Set.copyOf(operations),actionable?quote:"",reset,series);
        if(kind.equals("clarify")){
            if(!continues){clearPending();String id=hash(session+"\n"+started+"\n"+question);pending=new Reference(id,question,started,null);references.put(id,pending);}
            pendingScopes=Set.copyOf(scopes);pendingOperations=Set.copyOf(operations);relatedDiscussion=true;
        }else if(kind.equals("none")){if(continues)relatedDiscussion=true;}
        else if(kind.equals("reject")||actionable&&!continues)clearPending();
        return decision;
    }
    private static String plain(String value){return value.replaceAll("(?s)```.*?(?:```|\\z)|~~~.*?(?:~~~|\\z)","").replaceAll("(?m)^\\h*>.*$","").replaceAll("`[^`]*`|\"[^\"]*\"|'[^']*'|“[^”]*”|‘[^’]*’","");}
    private static String text(JsonObject args,String key,int limit){
        JsonElement value=args.get(key);if(value==null||!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString()||value.getAsString().length()>limit)throw new IllegalArgumentException("변경 의도 문자열을 확인해 주세요.");return value.getAsString();
    }
    private static boolean flag(JsonObject args,String key){JsonElement value=args.get(key);if(value==null||!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isBoolean())throw new IllegalArgumentException("변경 범위 값을 확인해 주세요.");return value.getAsBoolean();}
    private static Set<String> values(JsonObject args,String key,Set<String> allowed){
        JsonElement value=args.get(key);if(value==null||!value.isJsonArray()||value.getAsJsonArray().size()>allowed.size())throw new IllegalArgumentException("변경 범위를 확인해 주세요.");
        Set<String> result=new HashSet<>();for(JsonElement entry:value.getAsJsonArray())if(!entry.isJsonPrimitive()||!entry.getAsJsonPrimitive().isString()||!allowed.contains(entry.getAsString())||!result.add(entry.getAsString()))throw new IllegalArgumentException("허용된 변경 범위를 한 번씩만 지정해 주세요.");return result;
    }
    private static String hash(String text){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8))).substring(0,32);}catch(Exception impossible){throw new IllegalStateException(impossible);}}
}
