package dev.synesis.poc.pdf;
import com.google.gson.*;
import java.nio.file.*;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.check;
/** Durable session grouping, migration and full transcript retention on disposable data. */
public final class AssistantConversationsTest {
 static JsonObject snapshot(String id,int first,int count){
  JsonObject s=new JsonObject(),memory=new JsonObject();JsonArray turns=new JsonArray();
  for(int i=first;i<first+count;i++){JsonObject t=new JsonObject();t.addProperty("question","질문 "+i);t.addProperty("answer","답변 "+i);t.addProperty("timestampMs",1000L*i);turns.add(t);}
  memory.addProperty("documentId","home-assistant-v1");memory.add("turns",turns);s.addProperty("sessionId",id);s.add("memory",memory);
  for(String field:new String[]{"receipts","imageHistory","deliveryHistory"})s.add(field,new JsonObject());return s;
 }
 public static void main(String[] args)throws Exception{
  Path dir=Files.createTempDirectory("assistant-conversations-");AssistantConversations store=new AssistantConversations(dir);
  check(store.list().isEmpty(),"no initial records");
  JsonObject legacy=snapshot("legacy",1,3);legacy.getAsJsonObject("deliveryHistory").addProperty("1000",99);Files.writeString(dir.resolve("conversation.json"),legacy.toString());
  check(store.list().size()==1&&store.load("legacy").equals(legacy),"legacy single-file chat is selectable");
  store.save(snapshot("second",4,2));check(store.list().size()==2,"new chat preserves old flow");check(store.list().get(0).id().equals("second"),"newest message first");
  check(store.load("legacy").getAsJsonObject("deliveryHistory").get("1000").getAsInt()==99,"read receipts preserved");
  store.select("legacy");check(store.current().get("sessionId").getAsString().equals("legacy"),"selection persists across restart");
  store.save(snapshot("legacy",3,2));JsonObject resumed=store.load("legacy");check(AssistantConversations.turns(resumed).size()==4,"resume merges overlapping bounded context without duplicates");
  check(resumed.getAsJsonObject("memory").getAsJsonArray("turns").size()==2,"model context remains bounded independently");
  check(store.load("second").getAsJsonObject("memory").getAsJsonArray("turns").size()==2,"other conversation unaffected");
  check(store.list().stream().filter(e->e.id().equals("legacy")).findFirst().orElseThrow().title().equals("질문 1"),"original first message supplies title");
  store.save(snapshot("empty",1,0));check(store.list().size()==2,"blank new chat not added to picker");
  AssistantConversations restarted=new AssistantConversations(dir);restarted.select("second");check(restarted.current().get("sessionId").getAsString().equals("second"),"old flow reopens after restart");
  for(int i=6;i<=75;i++)restarted.save(snapshot("second",i,1));check(AssistantConversations.turns(restarted.load("second")).size()==72,"full transcript outlives model and display limits");
  JsonObject full=snapshot("second",76,1);JsonArray display=full.getAsJsonObject("memory").getAsJsonArray("turns").deepCopy();display.get(0).getAsJsonObject().addProperty("answer","긴 답변 전체".repeat(2000));full.add("transcript",display);restarted.save(full);
  check(AssistantConversations.turns(restarted.load("second")).get(72).getAsJsonObject().get("answer").getAsString().length()>5000,"display history retains full answer independently of shortened API memory");
  boolean denied=false;try{store.load("../outside");}catch(IllegalArgumentException expected){denied=true;}check(denied,"IDs cannot escape history directory");
  String original=Files.readString(dir.resolve("conversations/legacy.json"));Files.writeString(dir.resolve("conversations/damaged.json"),"{broken");check(store.list().size()==2,"one damaged record does not hide healthy histories");check(Files.readString(dir.resolve("conversations/damaged.json")).equals("{broken"),"damaged history preserved");
  Files.writeString(dir.resolve("conversation.json"),"{broken");denied=false;try{store.save(snapshot("replacement",1,1));}catch(Exception expected){denied=true;}check(denied&&Files.readString(dir.resolve("conversation.json")).equals("{broken"),"damaged active file never overwritten");check(Files.readString(dir.resolve("conversations/legacy.json")).equals(original),"other archives preserved after failure");
  System.out.println("AssistantConversationsTest OK · grouping, legacy migration, restart, resume, metadata, 72-turn retention, corruption preservation");
 }
}
