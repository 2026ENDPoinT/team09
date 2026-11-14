package dev.synesis.poc;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;

/** Shared durable store for future notes, planner and academic features; independent of the current directory. */
public final class UserDataStore {
    public enum Area { NOTES, PLANNER, ACADEMIC }
    private UserDataStore() {}
    public static Path folder(Area area){return switch(area){case NOTES->AppPaths.notes();case PLANNER->AppPaths.planner();case ACADEMIC->AppPaths.academic();};}
    public static Path file(Area area,String id) {
        if(id==null || !id.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("데이터 식별자가 올바르지 않아요.");
        return folder(area).resolve(id+".json");
    }
    public static JsonObject read(Area area,String id) throws IOException {
        Path file=file(area,id);return Files.exists(file)?JsonParser.parseString(Files.readString(file)).getAsJsonObject():null;
    }
    public static synchronized void save(Area area,String id,JsonObject value) throws IOException {
        Path file=file(area,id);Files.createDirectories(file.getParent());
        Path temp=Files.createTempFile(file.getParent(),"user-data-",".tmp");
        try{
            Files.writeString(temp,new GsonBuilder().setPrettyPrinting().create().toJson(value));
            try{Files.move(temp,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException e){Files.move(temp,file,StandardCopyOption.REPLACE_EXISTING);}
        }finally{Files.deleteIfExists(temp);}
    }
}
