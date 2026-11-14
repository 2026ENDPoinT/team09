package dev.synesis.poc.planner;

import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Offline persistence and recurrence contracts; always uses a disposable store. */
public final class PlannerStoreTest {
    static int checks;
    static void check(boolean condition,String message){checks++;if(!condition)throw new AssertionError(message);}
    static Event event(String id,LocalDateTime start,LocalDateTime end,Repeat repeat){return new Event(id,"미적분 중간고사","계산기와 학생증",start,end,false,EventColor.TEAL,List.of(),true,repeat,10);}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planner-test-");System.setProperty("synesis.dataRoot",root.toString());
        PlannerStore store=new PlannerStore();check(store.file().equals(root.resolve("planner/planner.json")),"shared user-data path");check(store.load().equals(State.empty()),"no example data on first run");check(!store.load().notificationsEnabled(),"notifications are not enabled on first run");
        Tag tag=new Tag("exam","시험");store.saveTags(List.of(),List.of(tag));
        Event exam=new Event("event1","미적분 중간고사","3–6장 복습",LocalDateTime.of(2026,10,22,10,0),LocalDateTime.of(2026,10,22,11,30),false,EventColor.BLUE,List.of("exam"),true,Repeat.NONE,10);
        store.saveEvent(exam);Task task=new Task("task","개념 복습",LocalDate.of(2026,10,17),"30분",false);store.saveTask(task);store.toggleTask("task");store.saveGoal(new Goal("week:2026-10-12","강의 복습",3,2));
        State loaded=new PlannerStore(store.file()).load();check(loaded.events().get(0).equals(exam),"event fields survive restart");check(loaded.tasks().get(0).completed(),"completed task survives restart");check(loaded.goals().get(0).completed()==2,"goal survives restart");check(Files.exists(store.file().resolveSibling("planner.json.bak")),"previous valid document retained");
        store.saveTags(List.of(tag),List.of(new Tag("exam","중간고사")));check(store.load().events().get(0).tagIds().equals(List.of("exam")),"renaming keeps stable references");
        store.saveTags(List.of(new Tag("exam","중간고사")),List.of());check(store.load().events().get(0).tagIds().isEmpty(),"deletion removes only tag references");check(store.load().events().get(0).title().equals(exam.title()),"tag deletion preserves event");
        ExecutorService pool=Executors.newFixedThreadPool(4);List<Future<?>> writes=new ArrayList<>();for(int i=0;i<30;i++){int n=i;writes.add(pool.submit(()->{try{new PlannerStore(store.file()).saveTask(new Task("parallel-"+n,"할 일 "+n,task.date(),"",false));}catch(Exception e){throw new RuntimeException(e);}}));}for(Future<?> write:writes)write.get();pool.shutdown();check(store.load().tasks().size()==31,"independent store instances retain concurrent writes");
        PlannerStore other=new PlannerStore(root.resolve("conflicts.json"));Tag a=new Tag("a","수업"),b=new Tag("b","시험");other.saveTags(List.of(),List.of(a));other.saveTags(List.of(a),List.of(a,b));other.saveTags(List.of(a),List.of(new Tag("a","강의")));check(other.load().tags().size()==2,"tag edit preserves another editor's new tags");
        Event month=event("month",LocalDateTime.of(2024,1,31,9,0),LocalDateTime.of(2024,1,31,10,0),Repeat.MONTHLY);State s=new State(0,List.of(month),List.of(),List.of(),List.of(),true,Set.of());
        List<Occurrence> monthly=occurrences(s,LocalDate.of(2024,2,1),LocalDate.of(2024,4,1));check(monthly.size()==2&&monthly.get(0).start().getDayOfMonth()==29&&monthly.get(1).start().getDayOfMonth()==31,"month end clamps without drifting March");
        Event overnight=event("night",LocalDateTime.of(2026,10,17,23,0),LocalDateTime.of(2026,10,18,0,0),Repeat.NONE);s=new State(0,List.of(overnight),List.of(),List.of(),List.of(),true,Set.of());check(occurrences(s,LocalDate.of(2026,10,18),LocalDate.of(2026,10,19)).isEmpty(),"midnight end is exclusive");
        Event daily=event("daily",LocalDateTime.of(2000,1,1,9,0),LocalDateTime.of(2000,1,1,10,0),Repeat.DAILY);s=new State(0,List.of(daily),List.of(),List.of(),List.of(),true,Set.of());check(occurrences(s,LocalDate.of(2026,10,12),LocalDate.of(2026,10,19)).size()==7,"old daily recurrence jumps to requested week");
        store.deleteEvent("event1");check(store.load().events().isEmpty(),"event deletion persisted");store.deleteTask("task");check(store.load().tasks().size()==30,"task deletion preserves unrelated tasks");
        String invalid="{broken planner data";Files.writeString(store.file(),invalid);try{store.saveTask(task);throw new AssertionError("corrupt file must not be replaced");}catch(java.io.IOException expected){checks++;}check(Files.readString(store.file()).equals(invalid),"corrupt original preserved");
        Files.writeString(store.file(),"{\"format\":\"synesis-planner\",\"version\":99}");String newer=Files.readString(store.file());try{store.saveTask(task);throw new AssertionError("newer schema must remain intact");}catch(java.io.IOException expected){checks++;}check(Files.readString(store.file()).equals(newer),"unknown schema preserved");
        System.out.println("PASS: "+checks+" planner persistence, concurrency and recurrence checks");
    }
}
