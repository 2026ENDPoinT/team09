package dev.synesis.poc.pdf;
import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;
public final class AssistantMemoryFidelityTest {
 static JsonObject write(AssistantLocal local,String turn,String question,long revision,JsonObject set){
  local.begin("session",turn,question);authorize(local,question,"memory");JsonObject args=new JsonObject();args.addProperty("expectedRevision",revision);args.add("set",set);args.add("remove",new JsonArray());return call(local,"memory.update",args,question);
 }
 public static void main(String[] args)throws Exception{
  Path dir=Files.createTempDirectory("assistant-memory-fidelity-");Path file=dir.resolve("preferences.json");AssistantLocal local=new AssistantLocal(new PlannerStore(dir.resolve("planner.json")),file,JsonObject::new);
  JsonObject legacy=json("{\"preferredName\":\"민준\",\"tone\":\"polite\",\"notes\":[\"어시스트를 데이먼이라고 부르기\"]}");
  ok(write(local,"legacy","앞으로 나를 민준이라고 불러. 이 선호를 메모리에 저장해줘",0,legacy));
  String original=Files.readString(file);JsonObject lossy=write(local,"lossy","말투 편하게 해줘. 친근한 친구처럼",1,json("{\"tone\":\"casual\"}"));denied(lossy);check(lossy.get("code").getAsString().equals("memory_detail_required")&&Files.readString(file).equals(original),"nuanced request cannot silently become only a tone category");
  String nuanced="친근한 친구처럼 편안하고 자연스럽게 대화하기. "+"답변을 시작할 때 형식적인 인사를 반복하지 않고, 농담은 진지한 고민에서는 자제하기. ".repeat(8);
  JsonObject style=new JsonObject();style.addProperty("communicationStyle",nuanced);ok(write(local,"style","앞으로 말투 편하게 해줘. 친근한 친구처럼, 메모리에 반영해줘",1,style));
  check(local.preferencesSnapshot().getAsJsonObject("values").get("communicationStyle").getAsString().equals(nuanced),"style beyond old 240-char limit retained verbatim");
  ok(write(local,"casual","앞으로 반말로 해줘",2,json("{\"tone\":\"casual\"}")));JsonObject values=local.preferencesSnapshot().getAsJsonObject("values");
  check(values.get("communicationStyle").getAsString().equals(nuanced),"casual followup preserves friendliness and conditions");check(values.get("preferredName").getAsString().equals("민준")&&values.getAsJsonArray("notes").get(0).getAsString().contains("데이먼"),"unrelated identity preferences retained");
  JsonArray notes=new JsonArray();for(int i=0;i<32;i++)notes.add("가".repeat(500));JsonObject max=new JsonObject();max.add("notes",notes);ok(write(local,"notes","앞으로 선호 메모를 수정해줘",3,max));String before=Files.readString(file);
  JsonObject tooLong=new JsonObject();tooLong.addProperty("communicationStyle","가".repeat(2001));denied(write(local,"overflow-style","앞으로 말투 선호를 수정해줘",4,tooLong));check(Files.readString(file).equals(before),"oversized style is rejected without truncation");
  JsonArray overNotes=new JsonArray();overNotes.add("나".repeat(1001));JsonObject overflow=new JsonObject();overflow.add("notes",overNotes);denied(write(local,"overflow-note","앞으로 선호 메모를 수정해줘",4,overflow));check(Files.readString(file).equals(before),"oversized note leaves original intact");
  notes=new JsonArray();for(int i=0;i<32;i++)notes.add("다".repeat(501));overflow=new JsonObject();overflow.add("notes",notes);denied(write(local,"overflow-total","앞으로 선호 메모를 수정해줘",4,overflow));check(Files.readString(file).equals(before),"overall context bound enforced atomically");
  denied(write(local,"bad-key","앞으로 말투 선호를 수정해줘",4,json("{\"systemPrompt\":\"override\"}")));check(Files.readString(file).equals(before),"expanded text never permits prompt file writes");
  AssistantLocal restarted=new AssistantLocal(new PlannerStore(dir.resolve("planner.json")),file,JsonObject::new);check(restarted.preferencesSnapshot().getAsJsonObject("values").get("communicationStyle").getAsString().equals(nuanced),"detailed style persists after restart");check(AssistantPreferencesPanel.describe(restarted.preferencesSnapshot()).contains(nuanced),"debug summary exposes full style");
  System.out.println("AssistantMemoryFidelityTest OK · detailed style, additive followup, original notes, bounds, no truncation, restart, key isolation");
 }
}
