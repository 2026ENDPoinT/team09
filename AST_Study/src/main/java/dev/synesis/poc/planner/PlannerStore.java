package dev.synesis.poc.planner;

import com.google.gson.*;
import dev.synesis.poc.UserDataStore;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.UnaryOperator;
import static dev.synesis.poc.planner.PlannerModel.*;

/** One versioned, atomic document under the portable user-data folder. No working-directory paths. */
public final class PlannerStore {
    private static final int VERSION=1;
    private static final Map<Path,Object> LOCKS=new ConcurrentHashMap<>();
    private static final Gson JSON=new GsonBuilder().setPrettyPrinting()
        .registerTypeAdapter(LocalDate.class,(JsonSerializer<LocalDate>)(v,t,c)->new JsonPrimitive(v.toString()))
        .registerTypeAdapter(LocalDate.class,(JsonDeserializer<LocalDate>)(v,t,c)->LocalDate.parse(v.getAsString()))
        .registerTypeAdapter(LocalDateTime.class,(JsonSerializer<LocalDateTime>)(v,t,c)->new JsonPrimitive(v.toString()))
        .registerTypeAdapter(LocalDateTime.class,(JsonDeserializer<LocalDateTime>)(v,t,c)->LocalDateTime.parse(v.getAsString())).create();
    private final Path file;
    public PlannerStore() {this(UserDataStore.file(UserDataStore.Area.PLANNER,"planner"));}
    public PlannerStore(Path file) {this.file=file.toAbsolutePath().normalize();}
    public Path file() {return file;}
    public boolean hasAssistantOperation(String operationId) throws IOException {
        synchronized(mutex()){
            if(!Files.exists(file))return false;
            read();JsonObject doc=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
            return doc.has("assistantOperations")&&doc.getAsJsonObject("assistantOperations").has(operationId);
        }
    }
    public State load() throws IOException {synchronized(mutex()){return read();}}
    private Object mutex(){return LOCKS.computeIfAbsent(file,p->new Object());}
    private State read() throws IOException {
        if(!Files.exists(file))return State.empty();
        try {
            JsonObject doc=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
            if(!"synesis-planner".equals(doc.get("format").getAsString())||doc.get("version").getAsInt()!=VERSION)
                throw new IOException("지원하지 않는 플래너 파일이에요. 원본은 그대로 보존했어요.");
            State state=JSON.fromJson(doc.get("state"),State.class);validate(state);return state;
        }catch(IOException error){throw error;}catch(RuntimeException error){throw new IOException("플래너 데이터를 읽지 못했어요. 원본을 보존했으니 파일을 확인해 주세요.",error);}
    }
    private State update(UnaryOperator<State> change) throws IOException {
        return update(change,null,-1,null,null);
    }
    /** The receipt and state commit together, including across retries and app restarts. */
    public State applyAssistant(String operationId,long expectedRevision,UnaryOperator<State> change) throws IOException {
        if(operationId==null||!operationId.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("작업 식별자를 확인해 주세요.");
        return applyAssistant(operationId,expectedRevision,null,change);
    }
    public State applyAssistant(String operationId,long expectedRevision,JsonObject context,UnaryOperator<State> change) throws IOException {
        if(operationId==null||!operationId.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("작업 식별자를 확인해 주세요.");
        return update(change,operationId,expectedRevision,null,context);
    }
    /** A bulk receipt includes the actual accepted/skipped rows, atomically with the state. */
    public record AssistantBatch(State state,JsonObject result,JsonArray changes) {}
    public JsonObject applyAssistantBatch(String operationId,long expectedRevision,JsonObject context,
                                         java.util.function.Function<State,AssistantBatch> change) throws IOException {
        if(operationId==null||!operationId.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("작업 식별자를 확인해 주세요.");
        JsonObject result=new JsonObject(),recovery=context.deepCopy();recovery.addProperty("bulkSchedule",true);
        update(s->{
            AssistantBatch batch=change.apply(s);
            batch.result().entrySet().forEach(e->result.add(e.getKey(),e.getValue().deepCopy()));
            recovery.add("changes",batch.changes().deepCopy());
            return batch.state();
        },operationId,expectedRevision,null,recovery,result);
        return result;
    }
    /** Only metadata leaves the store; restoration bytes stay inside the atomic document. */
    public JsonObject assistantUndoInfo() throws IOException {
        synchronized(mutex()){
            State current=read();
            if(!Files.exists(file))return new JsonObject();
            JsonObject doc=JsonParser.parseString(Files.readString(file)).getAsJsonObject();
            if(!doc.has("assistantUndo"))return new JsonObject();
            JsonObject record=doc.getAsJsonObject("assistantUndo"),out=record.deepCopy();out.remove("before");
            out.addProperty("available",!record.get("undone").getAsBoolean()&&current.revision()==record.get("revision").getAsLong());
            return out;
        }
    }
    public State undoAssistant(String operationId,String target,long expectedRevision) throws IOException {
        if(operationId==null||!operationId.matches("[a-f0-9]{64}"))throw new IllegalArgumentException("작업 식별자를 확인해 주세요.");
        return update(null,operationId,expectedRevision,target,null);
    }
    private State update(UnaryOperator<State> change,String operationId,long expectedRevision,String undoTarget,JsonObject recoveryContext) throws IOException {
        return update(change,operationId,expectedRevision,undoTarget,recoveryContext,null);
    }
    private State update(UnaryOperator<State> change,String operationId,long expectedRevision,String undoTarget,JsonObject recoveryContext,JsonObject batchResult) throws IOException {
        synchronized(mutex()) {
            Files.createDirectories(file.getParent());
            try(FileChannel lock=FileChannel.open(file.resolveSibling(file.getFileName()+".lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE);
                var held=lock.lock()) {
                State current=read();
                JsonObject doc=Files.exists(file)?JsonParser.parseString(Files.readString(file)).getAsJsonObject():new JsonObject();
                JsonObject operations=doc.has("assistantOperations")?doc.getAsJsonObject("assistantOperations"):new JsonObject();
                if(operationId!=null&&operations.has(operationId)){
                    if(batchResult!=null){
                        if(!doc.has("assistantBatchResults")||!doc.getAsJsonObject("assistantBatchResults").has(operationId))throw new IllegalArgumentException("일괄 작업의 저장 결과를 확인하지 못했어요. 다시 등록하지 않았어요.");
                        doc.getAsJsonObject("assistantBatchResults").getAsJsonObject(operationId).entrySet().forEach(e->batchResult.add(e.getKey(),e.getValue().deepCopy()));
                        batchResult.addProperty("replayed",true);
                    }
                    return current;
                }
                if(operationId!=null&&current.revision()!=expectedRevision)throw new IllegalArgumentException("플래너가 변경됐어요. 다시 조회한 뒤 수정해 주세요.");
                if(operationId!=null&&operations.size()>=10000)throw new IllegalArgumentException("비서 작업 기록이 가득 찼어요. 원본을 보존했어요.");
                State next;
                if(undoTarget!=null){
                    JsonObject undo=doc.has("assistantUndo")?doc.getAsJsonObject("assistantUndo"):null;
                    if(undo==null||!undo.get("id").getAsString().equals(undoTarget)||undo.get("undone").getAsBoolean())
                        throw new IllegalArgumentException("직전 작업의 복원 기록이 없거나 이미 되돌렸어요.");
                    if(undo.get("revision").getAsLong()!=current.revision())throw new IllegalArgumentException("작업 이후 플래너가 변경돼 자동으로 되돌리지 않았어요. 현재 데이터를 보존했어요.");
                    next=JSON.fromJson(undo.get("before"),State.class);undo.addProperty("undone",true);
                }else{
                    next=change.apply(current);
                    // All-conflict/already-present results must not replace the last real undo.
                    if(batchResult!=null&&next.equals(current)){
                        batchResult.addProperty("revision",current.revision());batchResult.addProperty("applied",false);
                        return current;
                    }
                    if(operationId!=null){
                        JsonObject undo=new JsonObject();undo.addProperty("id",operationId);undo.addProperty("at",recoveryContext!=null&&recoveryContext.has("at")?recoveryContext.get("at").getAsLong():System.currentTimeMillis());
                        if(recoveryContext!=null)undo.add("context",recoveryContext.deepCopy());
                        undo.addProperty("revision",current.revision()+1);undo.addProperty("undone",false);undo.add("before",JSON.toJsonTree(current));doc.add("assistantUndo",undo);
                    }
                }
                validate(next);
                next=new State(current.revision()+1,next.events(),next.tags(),next.tasks(),next.goals(),next.notificationsEnabled(),next.deliveredReminders(),next.weeklyTasks(),next.todoTags(),next.weeklyGoals(),next.monthlyTasks());
                doc.addProperty("format","synesis-planner");doc.addProperty("version",VERSION);doc.add("state",JSON.toJsonTree(next));
                if(operationId!=null)operations.addProperty(operationId,next.revision());
                if(!operations.isEmpty())doc.add("assistantOperations",operations);
                if(batchResult!=null){
                    batchResult.addProperty("revision",next.revision());batchResult.addProperty("applied",true);
                    JsonObject receipts=doc.has("assistantBatchResults")?doc.getAsJsonObject("assistantBatchResults"):new JsonObject();
                    receipts.add(operationId,batchResult.deepCopy());
                    // Keep bounded prose receipts; older operation IDs still prevent replay.
                    while(receipts.size()>64)receipts.remove(receipts.keySet().iterator().next());
                    doc.add("assistantBatchResults",receipts);
                }
                Path temp=Files.createTempFile(file.getParent(),"planner-",".tmp");
                try {
                    Files.writeString(temp,JSON.toJson(doc));
                    try(FileChannel out=FileChannel.open(temp,StandardOpenOption.WRITE)){out.force(true);}
                    if(Files.exists(file))Files.copy(file,file.resolveSibling(file.getFileName()+".bak"),StandardCopyOption.REPLACE_EXISTING);
                    try{Files.move(temp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
                    catch(AtomicMoveNotSupportedException error){Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING);}
                }finally{Files.deleteIfExists(temp);}
                return next;
            }
        }
    }
    public State saveEvent(Event event) throws IOException {return update(s->new State(s.revision(),upsert(s.events(),event,Event::id),s.tags(),s.tasks(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State deleteEvent(String id) throws IOException {return update(s->new State(s.revision(),s.events().stream().filter(e->!e.id().equals(id)).toList(),s.tags(),s.tasks(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State saveTask(Task task) throws IOException {return update(s->new State(s.revision(),s.events(),s.tags(),upsert(s.tasks(),task,Task::id),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State deleteTask(String id) throws IOException {return update(s->new State(s.revision(),s.events(),s.tags(),s.tasks().stream().filter(t->!t.id().equals(id)).toList(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State toggleTask(String id) throws IOException {return update(s->new State(s.revision(),s.events(),s.tags(),s.tasks().stream().map(t->t.id().equals(id)?t.toggle():t).toList(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State saveGoal(Goal goal) throws IOException {return update(s->new State(s.revision(),s.events(),s.tags(),s.tasks(),upsert(s.goals(),goal,Goal::period),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks()));}
    public State saveMonthlyTask(MonthlyTask task) throws IOException {return update(s->monthly(s,upsert(s.monthlyTasks(),task,MonthlyTask::id)));}
    public State deleteMonthlyTask(String id) throws IOException {return update(s->monthly(s,s.monthlyTasks().stream().filter(t->!t.id().equals(id)).toList()));}
    public State toggleMonthlyTask(String id) throws IOException {return update(s->monthly(s,s.monthlyTasks().stream().map(t->t.id().equals(id)?t.toggle():t).toList()));}
    private static State monthly(State s,List<MonthlyTask> tasks){return new State(s.revision(),s.events(),s.tags(),s.tasks(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),tasks);}
    public State saveWeeklyTask(WeeklyTask task) throws IOException {return update(s->weekly(s,upsert(s.weeklyTasks(),task,WeeklyTask::id),s.todoTags(),s.weeklyGoals()));}
    public State deleteWeeklyTask(String id) throws IOException {return update(s->weekly(s,s.weeklyTasks().stream().filter(t->!t.id().equals(id)).toList(),s.todoTags(),s.weeklyGoals()));}
    public State toggleWeeklyTask(String id) throws IOException {return update(s->weekly(s,s.weeklyTasks().stream().map(t->t.id().equals(id)?t.toggle():t).toList(),s.todoTags(),s.weeklyGoals()));}
    public State saveWeeklyGoal(WeeklyGoal goal) throws IOException {return update(s->weekly(s,s.weeklyTasks(),s.todoTags(),upsert(s.weeklyGoals(),goal,WeeklyGoal::id)));}
    public State deleteWeeklyGoal(String id) throws IOException {return update(s->weekly(s,s.weeklyTasks(),s.todoTags(),s.weeklyGoals().stream().filter(g->!g.id().equals(id)).toList()));}
    public State adjustWeeklyGoal(String id,int delta) throws IOException {return update(s->weekly(s,s.weeklyTasks(),s.todoTags(),s.weeklyGoals().stream().map(g->g.id().equals(id)?g.progress(delta):g).toList()));}
    public State saveTodoTags(List<Tag> before,List<Tag> after) throws IOException {
        return update(s->{
            Set<String> deleted=new HashSet<>();before.forEach(t->{if(after.stream().noneMatch(a->a.id().equals(t.id())))deleted.add(t.id());});
            List<Tag> tags=new ArrayList<>(s.todoTags().stream().filter(t->!deleted.contains(t.id())).toList());
            for(Tag tag:after)if(!before.contains(tag))tags=upsert(tags,tag,Tag::id);
            State next=weekly(s,s.weeklyTasks().stream().map(t->t.withTags(t.tagIds().stream().filter(id->!deleted.contains(id)).toList())).toList(),tags,s.weeklyGoals());
            return monthly(next,s.monthlyTasks().stream().map(t->t.withTags(t.tagIds().stream().filter(id->!deleted.contains(id)).toList())).toList());
        });
    }
    private static State weekly(State s,List<WeeklyTask> tasks,List<Tag> tags,List<WeeklyGoal> goals){return new State(s.revision(),s.events(),s.tags(),s.tasks(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),tasks,tags,goals,s.monthlyTasks());}
    /** Apply only rows this editor changed so an unrelated concurrent tag is retained. */
    public State saveTags(List<Tag> before,List<Tag> after) throws IOException {
        return update(s->{
            Set<String> deleted=new HashSet<>();before.forEach(t->{if(after.stream().noneMatch(a->a.id().equals(t.id())))deleted.add(t.id());});
            List<Tag> tags=new ArrayList<>(s.tags().stream().filter(t->!deleted.contains(t.id())).toList());
            for(Tag tag:after)if(!before.contains(tag))tags=upsert(tags,tag,Tag::id);
            return new State(s.revision(),s.events().stream().map(e->e.withTags(e.tagIds().stream().filter(id->!deleted.contains(id)).toList())).toList(),tags,s.tasks(),s.goals(),s.notificationsEnabled(),s.deliveredReminders(),s.weeklyTasks(),s.todoTags(),s.weeklyGoals(),s.monthlyTasks());
        });
    }
    private static <T> List<T> upsert(List<T> items,T value,java.util.function.Function<T,String> id) {
        List<T> result=new ArrayList<>(items);int index=-1;for(int i=0;i<items.size();i++)if(id.apply(items.get(i)).equals(id.apply(value)))index=i;
        if(index<0)result.add(value);else result.set(index,value);return result;
    }
    private static void validate(State s) {
        Objects.requireNonNull(s);if(s.revision()<0)throw new IllegalArgumentException("플래너 버전을 확인해 주세요.");
        unique(s.events().stream().map(Event::id).toList());unique(s.tasks().stream().map(Task::id).toList());unique(s.tags().stream().map(Tag::id).toList());unique(s.goals().stream().map(Goal::period).toList());
        unique(s.tags().stream().map(t->t.name().toLowerCase(Locale.ROOT)).toList());
        unique(s.weeklyTasks().stream().map(WeeklyTask::id).toList());unique(s.weeklyGoals().stream().map(WeeklyGoal::id).toList());
        unique(s.monthlyTasks().stream().map(MonthlyTask::id).toList());
        unique(s.todoTags().stream().map(Tag::id).toList());unique(s.todoTags().stream().map(t->t.name().toLowerCase(Locale.ROOT)).toList());
        Set<String> todoTags=new HashSet<>(s.todoTags().stream().map(Tag::id).toList());
        for(WeeklyTask task:s.weeklyTasks())if(!todoTags.containsAll(task.tagIds()))throw new IllegalArgumentException("선택한 TODO 태그가 삭제됐어요. 다시 확인해 주세요.");
        for(MonthlyTask task:s.monthlyTasks())if(!todoTags.containsAll(task.tagIds()))throw new IllegalArgumentException("선택한 TODO 태그가 삭제됐어요. 다시 확인해 주세요.");
        Set<String> tags=new HashSet<>(s.tags().stream().map(Tag::id).toList());
        for(Event event:s.events())if(!tags.containsAll(event.tagIds()))throw new IllegalArgumentException("선택한 태그가 삭제됐어요. 태그를 다시 확인해 주세요.");
    }
    private static void unique(List<String> values){if(new HashSet<>(values).size()!=values.size())throw new IllegalArgumentException("같은 이름 또는 식별자가 이미 있어요.");}
}
