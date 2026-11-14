package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Local conversation snapshots, separate from the bounded model context. */
final class AssistantConversations {
    record Entry(String id,String title,long updatedAt,int turns){}
    private final Path root;
    AssistantConversations(Path root){this.root=root;}
    private Path archive(String id){
        if(id==null||!id.matches("[a-zA-Z0-9-]{1,80}"))throw new IllegalArgumentException("대화 ID를 확인해 주세요.");
        return root.resolve("conversations").resolve(id+".json");
    }
    JsonObject current()throws Exception{return read(root.resolve("conversation.json"));}
    JsonObject load(String id)throws Exception{
        JsonObject value=read(archive(id));
        if(value==null){JsonObject active=current();if(active!=null&&id.equals(active.get("sessionId").getAsString()))value=active;}
        if(value==null)throw new IllegalArgumentException("대화 기록을 찾지 못했어요.");
        if(!id.equals(value.get("sessionId").getAsString()))throw new IllegalArgumentException("대화 기록의 ID가 달라요.");
        return value;
    }
    static JsonArray turns(JsonObject value){return value.has("transcript")?value.getAsJsonArray("transcript"):value.getAsJsonObject("memory").getAsJsonArray("turns");}
    private static boolean hasTurns(JsonObject value){return value!=null&&!turns(value).isEmpty();}
    synchronized void save(JsonObject snapshot)throws Exception{
        String id=snapshot.get("sessionId").getAsString();Path path=archive(id);
        // Migrate the old single-conversation file before a new chat replaces it.
        JsonObject active=current();
        if(hasTurns(active)&&!id.equals(active.get("sessionId").getAsString())){
            Path legacy=archive(active.get("sessionId").getAsString());
            if(!Files.exists(legacy))write(legacy,active);
        }
        JsonObject previous=read(path);
        if(previous==null&&active!=null&&id.equals(active.get("sessionId").getAsString()))previous=active;
        JsonObject saved=snapshot.deepCopy();JsonArray transcript=new JsonArray();Set<String> seen=new HashSet<>();
        if(hasTurns(previous))for(JsonElement turn:turns(previous)){transcript.add(turn.deepCopy());seen.add(key(turn));}
        for(JsonElement turn:turns(snapshot))if(seen.add(key(turn)))transcript.add(turn.deepCopy());
        saved.add("transcript",transcript);
        for(String field:List.of("receipts","imageHistory","deliveryHistory")){
            JsonObject merged=previous!=null&&previous.has(field)?previous.getAsJsonObject(field).deepCopy():new JsonObject();
            if(snapshot.has(field))snapshot.getAsJsonObject(field).entrySet().forEach(e->merged.add(e.getKey(),e.getValue().deepCopy()));saved.add(field,merged);
        }
        if(!transcript.isEmpty())write(path,saved);
        write(root.resolve("conversation.json"),saved);
    }
    synchronized JsonObject select(String id)throws Exception{
        JsonObject selected=load(id),active=current();
        if(hasTurns(active)){Path previous=archive(active.get("sessionId").getAsString());if(!Files.exists(previous))write(previous,active);}
        write(root.resolve("conversation.json"),selected);return selected;
    }
    List<Entry> list()throws Exception{
        Map<String,Entry> entries=new HashMap<>();Path directory=root.resolve("conversations");
        if(Files.isDirectory(directory))try(var files=Files.list(directory)){
            for(Path file:files.filter(p->p.getFileName().toString().endsWith(".json")).toList()){
                try{add(entries,read(file));}catch(Exception ignored){/* Preserve damaged records; other chats remain selectable. */}
            }
        }
        add(entries,current());
        return entries.values().stream().sorted(Comparator.comparingLong(Entry::updatedAt).reversed()).toList();
    }
    private static void add(Map<String,Entry> entries,JsonObject value){
        if(!hasTurns(value))return;JsonArray turns=turns(value);JsonObject first=turns.get(0).getAsJsonObject(),last=turns.get(turns.size()-1).getAsJsonObject();
        String title=first.get("question").getAsString().replaceAll("\\s+"," ").strip();
        if(title.length()>48)title=title.substring(0,48)+"…";
        String id=value.get("sessionId").getAsString();entries.put(id,new Entry(id,title,last.has("timestampMs")?last.get("timestampMs").getAsLong():0,turns.size()));
    }
    private static String key(JsonElement turn){JsonObject o=turn.getAsJsonObject();return o.has("timestampMs")?o.get("timestampMs").getAsString():o.toString();}
    private static JsonObject read(Path file)throws Exception{
        if(!Files.exists(file))return null;
        if(Files.size(file)>32_000_000)throw new IllegalArgumentException("대화 기록의 크기를 확인해 주세요.");
        JsonObject value=JsonParser.parseString(Files.readString(file)).getAsJsonObject();value.get("sessionId").getAsString();
        for(JsonElement turn:value.getAsJsonObject("memory").getAsJsonArray("turns")){turn.getAsJsonObject().get("question").getAsString();turn.getAsJsonObject().get("answer").getAsString();}
        for(JsonElement turn:turns(value)){turn.getAsJsonObject().get("question").getAsString();turn.getAsJsonObject().get("answer").getAsString();}
        return value;
    }
    private static void write(Path file,JsonObject value)throws Exception{
        Files.createDirectories(file.getParent());Path temp=Files.createTempFile(file.getParent(),"conversation-",".tmp");
        try{Files.writeString(temp,value.toString());
            try{Files.move(temp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException e){Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING);}
        }finally{Files.deleteIfExists(temp);}
    }
}
