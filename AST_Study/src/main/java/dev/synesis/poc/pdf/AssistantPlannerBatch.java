package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Compact, finite recurrence rules expand locally, never into hundreds of model-written patches. */
final class AssistantPlannerBatch {
    static final int MAX_ENTRIES=50,MAX_OCCURRENCES=1000;
    private static final Set<String> FIELDS=Set.of("title","description","start","end","allDay","color","tags","important","repeat","through");
    private record Rule(Event template,List<String> tags,boolean fixedColor) {}
    private record Candidate(int rule,LocalDateTime start,LocalDateTime end) {}
    private final List<Rule> rules=new ArrayList<>();
    private final List<Candidate> candidates=new ArrayList<>();
    private final LocalDate from,to;

    AssistantPlannerBatch(JsonArray entries){
        if(entries.isEmpty()||entries.size()>MAX_ENTRIES)throw new IllegalArgumentException("일괄 등록 규칙은 한 번에 1~50개로 보내 주세요.");
        for(JsonElement element:entries){
            if(!element.isJsonObject())throw new IllegalArgumentException("일정 등록 규칙을 확인해 주세요.");
            JsonObject f=element.getAsJsonObject();
            if(!FIELDS.containsAll(f.keySet()))throw new IllegalArgumentException("허용되지 않은 일괄 일정 필드예요.");
            LocalDateTime start=LocalDateTime.parse(text(f,"start",null,40)),end=LocalDateTime.parse(text(f,"end",null,40));
            Repeat repeat=Repeat.valueOf(text(f,"repeat","NONE",20));
            LocalDate through=f.has("through")?LocalDate.parse(text(f,"through",null,10)):repeat==Repeat.NONE?start.toLocalDate():null;
            if(through==null)throw new IllegalArgumentException("반복 등록을 끝낼 날짜가 필요해요. 종료일을 확인해 주세요.");
            long days=ChronoUnit.DAYS.between(start.toLocalDate(),through);
            if(days<0||days>365||through.getYear()>2200)throw new IllegalArgumentException("반복 등록 기간은 시작일부터 최대 366일이에요.");
            if(repeat==Repeat.NONE&&!through.equals(start.toLocalDate()))throw new IllegalArgumentException("반복하지 않는 일정의 종료일은 시작 날짜와 같아야 해요.");
            if(Duration.between(start,end).compareTo(Duration.ofDays(366))>0)throw new IllegalArgumentException("한 회차의 길이는 최대 366일이에요.");
            List<String> tags=new ArrayList<>();
            if(f.has("tags")){
                if(!f.get("tags").isJsonArray()||f.getAsJsonArray("tags").size()>12)throw new IllegalArgumentException("태그는 최대 12개예요.");
                for(JsonElement value:f.getAsJsonArray("tags")){
                    if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString())throw new IllegalArgumentException("태그 이름을 확인해 주세요.");
                    tags.add(new Tag("check",value.getAsString()).name());
                }
            }
            Event template=new Event("template",text(f,"title",null,200),text(f,"description","",10000),start,end,
                flag(f,"allDay",false),f.has("color")?EventColor.valueOf(text(f,"color",null,20)):EventColor.values()[java.util.concurrent.ThreadLocalRandom.current().nextInt(EventColor.values().length)],
                List.of(),flag(f,"important",false),repeat,-1);
            int rule=rules.size();rules.add(new Rule(template,List.copyOf(tags),f.has("color")));
            for(int index=0;;index++){
                LocalDateTime at=switch(repeat){case NONE->index==0?start:null;case DAILY->start.plusDays(index);case WEEKLY->start.plusWeeks(index);case MONTHLY->start.plusMonths(index);case YEARLY->start.plusYears(index);};
                if(at==null||at.toLocalDate().isAfter(through))break;
                LocalDateTime finish=at.plus(Duration.between(start,end));
                if(finish.getYear()>2200)throw new IllegalArgumentException("종료 날짜는 2200년까지 입력할 수 있어요.");
                candidates.add(new Candidate(rule,at,finish));
                if(candidates.size()>MAX_OCCURRENCES)throw new IllegalArgumentException("일괄 등록은 최대 1,000회차예요. 전체 기간을 나눠 주세요. 아직 저장하지 않았어요.");
            }
        }
        candidates.sort(Comparator.comparing(Candidate::start).thenComparingInt(Candidate::rule));
        from=candidates.stream().map(c->c.start().toLocalDate()).min(LocalDate::compareTo).orElseThrow();
        to=candidates.stream().map(c->c.end().toLocalDate().plusDays(c.end().toLocalTime().equals(LocalTime.MIDNIGHT)?0:1)).max(LocalDate::compareTo).orElseThrow();
        if(ChronoUnit.DAYS.between(from,to)>800)throw new IllegalArgumentException("일괄 등록의 전체 날짜 범위를 좁혀 주세요. 아직 저장하지 않았어요.");
    }

    PlannerStore.AssistantBatch apply(State state,String operation){
        List<Event> events=new ArrayList<>(state.events());List<Tag> tags=new ArrayList<>(state.tags());
        List<Occurrence> occupied=new ArrayList<>(occurrences(state,from,to));
        JsonObject result=new JsonObject();JsonArray summaries=new JsonArray(),blockers=new JsonArray(),changes=new JsonArray();
        Map<String,Integer> blockerIndices=new LinkedHashMap<>();
        for(Rule rule:rules){
            JsonObject summary=new JsonObject();summary.addProperty("title",rule.template().title());summary.addProperty("requestedCount",0);summary.addProperty("addedCount",0);summary.addProperty("alreadyPresentCount",0);
            summary.add("skipped",new JsonArray());summaries.add(summary);
        }
        int added=0,already=0,skipped=0,sequence=0;
        for(Candidate candidate:candidates){
            Rule rule=rules.get(candidate.rule());Event template=rule.template();JsonObject summary=summaries.get(candidate.rule()).getAsJsonObject();increment(summary,"requestedCount");
            List<Occurrence> overlaps=occupied.stream().filter(o->o.start().isBefore(candidate.end())&&o.end().isAfter(candidate.start())).toList();
            // Equivalent occupied slots are already fulfilled; do not duplicate or retag them.
            boolean present=overlaps.stream().anyMatch(o->o.start().equals(candidate.start())&&o.end().equals(candidate.end())&&o.event().title().equals(template.title())&&o.event().allDay()==template.allDay()&&
                new HashSet<>(o.event().tagIds().stream().map(id->tags.stream().filter(t->t.id().equals(id)).map(Tag::name).findFirst().orElse("").toLowerCase(Locale.ROOT)).toList()).equals(new HashSet<>(rule.tags().stream().map(s->s.toLowerCase(Locale.ROOT)).toList())));
            if(present){already++;increment(summary,"alreadyPresentCount");continue;}
            if(!overlaps.isEmpty()){
                Occurrence first=overlaps.getFirst();String key=first.key();Integer blocker=blockerIndices.get(key);
                if(blocker==null){
                    blocker=blockers.size();blockerIndices.put(key,blocker);JsonObject row=new JsonObject();
                    row.addProperty("id",first.event().id());row.addProperty("title",first.event().title());row.addProperty("start",first.start().toString());row.addProperty("end",first.end().toString());row.addProperty("repeat",first.event().repeat().name());row.addProperty("allDay",first.event().allDay());blockers.add(row);
                }
                JsonObject row=new JsonObject();row.addProperty("start",candidate.start().toString());row.addProperty("end",candidate.end().toString());row.addProperty("blocker",blocker);row.addProperty("conflictCount",overlaps.size());summary.getAsJsonArray("skipped").add(row);skipped++;continue;
            }
            String id=UUID.nameUUIDFromBytes((operation+":"+sequence++).getBytes(StandardCharsets.UTF_8)).toString();
            JsonObject tagFields=new JsonObject();JsonArray tagNames=new JsonArray();rule.tags().forEach(tagNames::add);tagFields.add("tags",tagNames);
            List<String> tagIds=AssistantLocal.resolveTags(tagFields,tags,operation);
            EventColor color=rule.fixedColor()?template.color():EventColor.values()[java.util.concurrent.ThreadLocalRandom.current().nextInt(EventColor.values().length)];
            Event event=new Event(id,template.title(),template.description(),candidate.start(),candidate.end(),template.allDay(),color,tagIds,template.important(),Repeat.NONE,-1);
            events.add(event);occupied.add(new Occurrence(event,event.start(),event.end()));added++;increment(summary,"addedCount");
            if(!summary.has("firstAdded"))summary.addProperty("firstAdded",candidate.start().toString());summary.addProperty("lastAdded",candidate.start().toString());
            JsonObject change=new JsonObject(),fields=new JsonObject();change.addProperty("entity","event");change.addProperty("operation","create");change.addProperty("id",id);
            fields.addProperty("title",event.title());fields.addProperty("start",event.start().toString());fields.addProperty("end",event.end().toString());change.add("fields",fields);changes.add(change);
        }
        result.addProperty("requestedCount",candidates.size());result.addProperty("addedCount",added);result.addProperty("alreadyPresentCount",already);result.addProperty("skippedCount",skipped);result.add("entries",summaries);result.add("blockers",blockers);
        // Preserve every excluded date. Never commit a result that cannot cross the existing RPC.
        if(result.toString().length()>170000)throw new IllegalArgumentException("충돌 안내가 너무 길어요. 등록 기간을 나눠 주세요. 아직 저장하지 않았어요.");
        State next=added==0?state:new State(state.revision(),events,tags,state.tasks(),state.goals(),state.notificationsEnabled(),state.deliveredReminders(),state.weeklyTasks(),state.todoTags(),state.weeklyGoals(),state.monthlyTasks());
        return new PlannerStore.AssistantBatch(next,result,changes);
    }
    private static void increment(JsonObject row,String key){row.addProperty(key,row.get(key).getAsInt()+1);}
    private static String text(JsonObject object,String key,String fallback,int max){
        if(!object.has(key)){if(fallback!=null)return fallback;throw new IllegalArgumentException(key+" 정보가 필요해요.");}
        JsonElement value=object.get(key);if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isString()||value.getAsString().length()>max||value.getAsString().isBlank()&&fallback==null)throw new IllegalArgumentException(key+" 값을 확인해 주세요.");return value.getAsString();
    }
    private static boolean flag(JsonObject object,String key,boolean fallback){if(!object.has(key))return fallback;JsonElement value=object.get(key);if(!value.isJsonPrimitive()||!value.getAsJsonPrimitive().isBoolean())throw new IllegalArgumentException(key+" 논리값을 확인해 주세요.");return value.getAsBoolean();}
}
