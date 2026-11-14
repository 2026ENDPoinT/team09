package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/** A PDF owns one current conversation. An empty snapshot is an explicit reset. */
final class TutorConversationStore {
    static Path path(Path folder){return folder.resolve("tutor-conversation.json");}
    static JsonObject read(Path folder)throws IOException{
        Path path=path(folder);
        if(!Files.exists(path))return new JsonObject();
        try {
            JsonObject value=JsonParser.parseString(Files.readString(path,StandardCharsets.UTF_8)).getAsJsonObject();
            value.getAsJsonObject("memory");
            for(JsonElement element:value.getAsJsonArray("turns")){
                JsonObject turn=element.getAsJsonObject();turn.get("question").getAsString();turn.get("marker").getAsString();
            }
            return value;
        }catch(RuntimeException invalid){throw new IOException("저장된 AI멘토 대화를 읽지 못했어요. 기존 기록은 보존했어요.",invalid);}
    }
    static void write(Path folder,JsonObject snapshot)throws IOException{
        Files.createDirectories(folder);Path temporary=Files.createTempFile(folder,"tutor-",".tmp");
        try{
            Files.writeString(temporary,new Gson().toJson(snapshot),StandardCharsets.UTF_8);
            try{Files.move(temporary,path(folder),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException unsupported){Files.move(temporary,path(folder),StandardCopyOption.REPLACE_EXISTING);}
        }finally{Files.deleteIfExists(temporary);}
    }
}
