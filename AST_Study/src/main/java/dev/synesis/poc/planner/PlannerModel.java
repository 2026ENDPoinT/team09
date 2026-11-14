package dev.synesis.poc.planner;

import java.time.*;
import java.time.temporal.*;
import java.util.*;

/** Calendar dates stay local; recurring events are expanded only for the requested range. */
public final class PlannerModel {
    private PlannerModel() {}
    public enum Repeat {
        NONE("반복 안 함"), DAILY("매일"), WEEKLY("매주"), MONTHLY("매월"), YEARLY("매년");
        private final String label;
        Repeat(String label) { this.label=label; }
        @Override public String toString() { return label; }
    }
    public enum EventColor {
        NAVY("네이비",0x002860), BLUE("블루",0x3b6fa5), TEAL("틸",0x287a75),
        OCHRE("오커",0xb78532), ROSE("로즈",0xbb6271), SLATE("슬레이트",0x75849a),
        PURPLE("퍼플",0x7656a8), GREEN("그린",0x3f8254), ORANGE("오렌지",0xd6752d),
        RED("레드",0xc44845), YELLOW("옐로",0xe9c85b), PINK("핑크",0xe59bb1);
        public final String label; public final int rgb;
        EventColor(String label,int rgb) { this.label=label;this.rgb=rgb; }
        @Override public String toString() {return label;}
    }
    public record Event(String id,String title,String description,LocalDateTime start,LocalDateTime end,
                        boolean allDay,EventColor color,List<String> tagIds,boolean important,Repeat repeat,int reminderMinutes) {
        public Event {
            requireId(id); title=title==null?"":title.strip(); description=description==null?"":description.strip();
            if(title.isEmpty()||title.length()>200)throw new IllegalArgumentException("일정 제목을 1~200자로 입력해 주세요.");
            if(description.length()>10000)throw new IllegalArgumentException("일정 설명은 10,000자까지 입력할 수 있어요.");
            Objects.requireNonNull(start);Objects.requireNonNull(end);Objects.requireNonNull(color);Objects.requireNonNull(repeat);
            if(!end.isAfter(start))throw new IllegalArgumentException("종료는 시작보다 뒤여야 해요.");
            if(start.getYear()<1900||end.getYear()>2200)throw new IllegalArgumentException("날짜는 1900년부터 2200년까지 입력해 주세요.");
            tagIds=List.copyOf(new LinkedHashSet<>(tagIds)); tagIds.forEach(PlannerModel::requireId);
            if(!Set.of(-1,0,5,10,30,60,1440).contains(reminderMinutes))throw new IllegalArgumentException("알림 시간을 확인해 주세요.");
            if(allDay&&(!start.toLocalTime().equals(LocalTime.MIDNIGHT)||!end.toLocalTime().equals(LocalTime.MIDNIGHT)))
                throw new IllegalArgumentException("종일 일정의 날짜를 확인해 주세요.");
        }
        public Event withTags(List<String> ids) {return new Event(id,title,description,start,end,allDay,color,ids,important,repeat,reminderMinutes);}
    }
    public record Tag(String id,String name) {
        public Tag {requireId(id);name=name==null?"":name.strip();if(name.isEmpty()||name.length()>30)throw new IllegalArgumentException("태그 이름을 1~30자로 입력해 주세요.");}
    }
    public record Task(String id,String title,LocalDate date,String detail,boolean completed) {
        public Task {requireId(id);title=title==null?"":title.strip();detail=detail==null?"":detail.strip();Objects.requireNonNull(date);
            if(title.isEmpty()||title.length()>200)throw new IllegalArgumentException("할 일을 1~200자로 입력해 주세요.");
            if(date.getYear()<1900||date.getYear()>2200)throw new IllegalArgumentException("날짜는 1900년부터 2200년까지 입력해 주세요.");
            if(detail.length()>1000)throw new IllegalArgumentException("설명은 1,000자까지 입력할 수 있어요.");}
        public Task toggle() {return new Task(id,title,date,detail,!completed);}
    }
    public record Goal(String period,String title,int target,int completed) {
        public Goal {Objects.requireNonNull(period);title=title==null?"":title.strip();if(title.isEmpty()||title.length()>200||target<1||target>100000||completed<0||completed>target)
            throw new IllegalArgumentException("목표 이름과 진행 수를 확인해 주세요.");}
    }
    /** Weekly TODOs have their own week and tag namespace; a deadline never determines visibility. */
    public record WeeklyTask(String id,String title,LocalDate deadline,LocalDate week,List<String> tagIds,boolean completed) {
        public WeeklyTask {
            requireId(id);title=title==null?"":title.strip();if(deadline!=null)validDate(deadline);validDate(week);week=weekStart(week);
            if(title.isEmpty()||title.length()>200)throw new IllegalArgumentException("TODO 제목을 1~200자로 입력해 주세요.");
            tagIds=List.copyOf(new LinkedHashSet<>(tagIds));tagIds.forEach(PlannerModel::requireId);
        }
        public WeeklyTask toggle(){return new WeeklyTask(id,title,deadline,week,tagIds,!completed);}
        public WeeklyTask withTags(List<String> ids){return new WeeklyTask(id,title,deadline,week,ids,completed);}
    }
    public record WeeklyGoal(String id,String title,LocalDate week,int target,int completed) {
        public WeeklyGoal {
            requireId(id);title=title==null?"":title.strip();validDate(week);week=weekStart(week);
            if(title.isEmpty()||title.length()>200||target<1||target>100000||completed<0||completed>target)
                throw new IllegalArgumentException("목표 제목과 횟수를 확인해 주세요.");
        }
        public WeeklyGoal progress(int delta){return new WeeklyGoal(id,title,week,target,(int)Math.max(0,Math.min((long)target,(long)completed+delta)));}
    }
    /** Monthly TODOs belong to a month independently of their optional deadline. */
    public record MonthlyTask(String id,String title,LocalDate deadline,LocalDate month,List<String> tagIds,boolean completed) {
        public MonthlyTask {
            requireId(id);title=title==null?"":title.strip();validDate(month);month=month.withDayOfMonth(1);
            if(deadline!=null)validDate(deadline);
            if(title.isEmpty()||title.length()>200)throw new IllegalArgumentException("TODO 제목을 1~200자로 입력해 주세요.");
            tagIds=List.copyOf(new LinkedHashSet<>(tagIds));tagIds.forEach(PlannerModel::requireId);
        }
        public MonthlyTask toggle(){return new MonthlyTask(id,title,deadline,month,tagIds,!completed);}
        public MonthlyTask withTags(List<String> ids){return new MonthlyTask(id,title,deadline,month,ids,completed);}
    }
    private static void validDate(LocalDate date){Objects.requireNonNull(date);if(date.getYear()<1900||date.getYear()>2200)throw new IllegalArgumentException("날짜는 1900년부터 2200년까지 입력해 주세요.");}
    // Legacy reminder fields remain in the file for lossless compatibility; no delivery implementation is active.
    public record State(long revision,List<Event> events,List<Tag> tags,List<Task> tasks,List<Goal> goals,
                        boolean notificationsEnabled,Set<String> deliveredReminders,
                        List<WeeklyTask> weeklyTasks,List<Tag> todoTags,List<WeeklyGoal> weeklyGoals,List<MonthlyTask> monthlyTasks) {
        public State {
            events=List.copyOf(events);tags=List.copyOf(tags);tasks=List.copyOf(tasks);goals=List.copyOf(goals);deliveredReminders=Set.copyOf(deliveredReminders);
            weeklyTasks=weeklyTasks==null?List.of():List.copyOf(weeklyTasks);todoTags=todoTags==null?List.of():List.copyOf(todoTags);
            monthlyTasks=monthlyTasks==null?List.of():List.copyOf(monthlyTasks);
            // Read old weekly goals without rewriting the file. Once saved, the new list is authoritative.
            weeklyGoals=weeklyGoals==null?goals.stream().filter(g->g.period().startsWith("week:"))
                .map(g->new WeeklyGoal("legacy-"+g.period().substring(5),g.title(),LocalDate.parse(g.period().substring(5)),g.target(),g.completed())).toList():List.copyOf(weeklyGoals);
        }
        public State(long revision,List<Event> events,List<Tag> tags,List<Task> tasks,List<Goal> goals,boolean notificationsEnabled,Set<String> deliveredReminders,List<WeeklyTask> weeklyTasks,List<Tag> todoTags,List<WeeklyGoal> weeklyGoals){this(revision,events,tags,tasks,goals,notificationsEnabled,deliveredReminders,weeklyTasks,todoTags,weeklyGoals,null);}
        public State(long revision,List<Event> events,List<Tag> tags,List<Task> tasks,List<Goal> goals,boolean notificationsEnabled,Set<String> deliveredReminders){this(revision,events,tags,tasks,goals,notificationsEnabled,deliveredReminders,null,null,null);}
        public static State empty() {return new State(0,List.of(),List.of(),List.of(),List.of(),false,Set.of());}
        public String tagName(String id) {return tags.stream().filter(t->t.id().equals(id)).map(Tag::name).findFirst().orElse("");}
    }
    /** End is exclusive, including for all-day events. */
    public record Occurrence(Event event,LocalDateTime start,LocalDateTime end) {
        public String key() {return event.id()+"@"+start;}
        public boolean on(LocalDate date) {return start.isBefore(date.plusDays(1).atStartOfDay())&&end.isAfter(date.atStartOfDay());}
    }
    public static String id() {return UUID.randomUUID().toString();}
    public static LocalDate weekStart(LocalDate date) {return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));}
    public static String period(LocalDate date,boolean monthly) {return monthly?"month:"+YearMonth.from(date):"week:"+weekStart(date);}
    public static String dDay(LocalDate today,LocalDate start) {long n=ChronoUnit.DAYS.between(today,start);return n==0?"D-day":n>0?"D-"+n:"D+"+(-n);}

    public static List<Occurrence> occurrences(State state,LocalDate from,LocalDate toExclusive) {
        if(!toExclusive.isAfter(from)||ChronoUnit.DAYS.between(from,toExclusive)>800)throw new IllegalArgumentException("조회 기간을 확인해 주세요.");
        List<Occurrence> result=new ArrayList<>();
        for(Event event:state.events()) {
            long span=ChronoUnit.DAYS.between(event.start().toLocalDate(),event.end().toLocalDate())+1;
            LocalDate first=from.minusDays(span);
            long index=initialIndex(event,first);
            // No unbounded expansion from the original start date, even for old daily events.
            for(; ;index++) {
                LocalDateTime start=at(event,index);
                if(start==null||!start.isBefore(toExclusive.atStartOfDay()))break;
                LocalDateTime end=start.plus(Duration.between(event.start(),event.end()));
                if(end.isAfter(from.atStartOfDay()))result.add(new Occurrence(event,start,end));
                if(event.repeat()==Repeat.NONE)break;
            }
        }
        result.sort(Comparator.comparing(Occurrence::start).thenComparing(o->o.event().title()).thenComparing(o->o.event().id()));
        return List.copyOf(result);
    }
    private static long initialIndex(Event event,LocalDate from) {
        LocalDate start=event.start().toLocalDate();
        long n=switch(event.repeat()) {
            case NONE->0;case DAILY->ChronoUnit.DAYS.between(start,from);
            case WEEKLY->ChronoUnit.DAYS.between(start,from)/7;
            case MONTHLY->ChronoUnit.MONTHS.between(YearMonth.from(start),YearMonth.from(from));
            case YEARLY->from.getYear()-start.getYear();
        };
        return Math.max(0,n-1);
    }
    private static LocalDateTime at(Event event,long index) {
        try {return switch(event.repeat()) {case NONE->index==0?event.start():null;case DAILY->event.start().plusDays(index);
            case WEEKLY->event.start().plusWeeks(index);case MONTHLY->event.start().plusMonths(index);case YEARLY->event.start().plusYears(index);};}
        catch(DateTimeException error){return null;}
    }
    private static void requireId(String id) {if(id==null||!id.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("플래너 식별자를 확인해 주세요.");}
}
