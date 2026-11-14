package dev.synesis.poc;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

/** One path contract for application resources, durable data, and disposable runtime state. */
public final class AppPaths {
    private static final String SCHEME = "synesis-data://";
    private AppPaths() {}
    private static Path configured(String property, String environment, Path fallback) {
        String value=System.getProperty(property);
        if(value==null || value.isBlank())value=System.getenv(environment);
        return (value==null || value.isBlank()?fallback:Path.of(value)).toAbsolutePath().normalize();
    }
    public static Path appRoot() {
        String override=System.getProperty("synesis.appRoot",System.getenv("SYNESIS_APP_ROOT"));
        if(override!=null && !override.isBlank()) {
            Path configured=Path.of(override).toAbsolutePath().normalize();
            if(!Files.isRegularFile(configured.resolve("scripts/pdf_pipeline.py")))throw new IllegalStateException("앱 실행 리소스를 찾지 못했어요.");
            return configured;
        }
        return installedRoot();
    }
    static Path installedRoot() {
        try {
            Path location=Path.of(AppPaths.class.getProtectionDomain().getCodeSource().getLocation().toURI());
            for(Path p=location;p!=null;p=p.getParent()) {
                Path packaged=p.resolve("Resources/workspace");
                if(Files.isRegularFile(packaged.resolve("scripts/pdf_pipeline.py")))return packaged;
                if(Files.isRegularFile(p.resolve("scripts/pdf_pipeline.py")))return p;
            }
        } catch(Exception ignored) { }
        Path fallback=Path.of(System.getProperty("user.dir")).toAbsolutePath().normalize();
        if(Files.isRegularFile(fallback.resolve("scripts/pdf_pipeline.py")))return fallback;
        throw new IllegalStateException("앱 실행 리소스를 찾지 못했어요.");
    }
    public static Path dataRoot() {return configured("synesis.dataRoot","SYNESIS_DATA_DIR",installedRoot().resolve(".ast-study-data"));}
    public static Path library() {return dataRoot().resolve("library");}
    public static Path account() {return dataRoot().resolve("account");}
    public static Path recordings() {return dataRoot().resolve("recordings");}
    public static Path lectureNotes() {return recordings().resolve("lecture-notes");}
    public static Path notes() {return dataRoot().resolve("notes");}
    public static Path planner() {return dataRoot().resolve("planner");}
    public static Path academic() {return dataRoot().resolve("academic");}
    public static Path settings() {return dataRoot().resolve("settings");}
    public static Path runtimeState() {return dataRoot().resolve(".runtime");}
    public static Path script(String name) {return appRoot().resolve("scripts").resolve(name);}
    public static Path document(String id) {
        if(id==null || !id.matches("[0-9a-f]{64}"))throw new IllegalArgumentException("문서 식별자가 올바르지 않아요.");
        return library().resolve(id);
    }
    public static Path documentNotes(String id) {return document(id).resolve("notes");}
    public static Path recordingParts(String documentId) {
        return documentId!=null && documentId.matches("[0-9a-f]{64}")
            ?document(documentId).resolve("recordings"):recordings().resolve("lectures");
    }
    public static Path accountForLibrary(Path library) {
        Path root=storageRoot(library);
        return root==null?library.toAbsolutePath().normalize().getParent():root.resolve("account");
    }
    public static Path storageRoot(Path path) {
        for(Path p=path.toAbsolutePath().normalize();p!=null;p=p.getParent()) {
            Path manifest=p.resolve("manifest.json");
            if(Files.isRegularFile(manifest))try {
                if("synesis-user-data".equals(JsonParser.parseString(Files.readString(manifest)).getAsJsonObject().get("format").getAsString()))return p;
            }catch(Exception ignored) { }
        }
        return null;
    }
    public static String reference(Path path) {
        Path absolute=path.toAbsolutePath().normalize(),root=storageRoot(absolute);
        return root!=null && absolute.startsWith(root)?SCHEME+root.relativize(absolute).toString().replace('\\','/'):absolute.toString();
    }
    public static Path stored(String value) {return stored(value,dataRoot());}
    public static Path stored(String value,Path anchor) {
        if(!value.startsWith(SCHEME))return Path.of(value).toAbsolutePath().normalize();
        Path root=storageRoot(anchor);if(root==null)root=dataRoot();
        String relative=value.substring(SCHEME.length());
        Path result=root.resolve(relative).normalize();
        if(relative.isBlank() || relative.contains("\\") || !result.startsWith(root))throw new IllegalArgumentException("사용자 데이터 경로가 올바르지 않아요.");
        return result;
    }
    /** Pass identical roots to every Python worker; its cwd no longer defines user storage. */
    public static ProcessBuilder process(ProcessBuilder builder) {
        builder.environment().put("SYNESIS_APP_ROOT",appRoot().toString());
        builder.environment().put("SYNESIS_DATA_DIR",dataRoot().toString());
        // An existing desktop JVM keeps its previous Python reading policy until restart.
        builder.environment().put("SYNESIS_STUDY_READING_POLICY","coherent-chart-code-teaching-v1");
        builder.environment().put("SYNESIS_STUDY_OWNERSHIP_POLICY","off");
        builder.environment().put("SYNESIS_LEARNING_FLOW_POLICY","off");
        builder.environment().put("SYNESIS_TEACHING_CONTENT_POLICY","off");
        String credentials=System.getProperty("synesis.credentialsFile");
        if(credentials!=null)builder.environment().put("SYNESIS_CREDENTIALS_FILE",credentials);
        if(Boolean.getBoolean("ast.study.standalone"))builder.environment().put("PYTHONDONTWRITEBYTECODE","1");
        return builder;
    }
    public static void prepare() throws Exception {
        Path manifest=dataRoot().resolve("manifest.json");
        if(Files.isRegularFile(manifest)) {
            JsonObject value=JsonParser.parseString(Files.readString(manifest)).getAsJsonObject();
            if(!"synesis-user-data".equals(value.get("format").getAsString()) || value.get("version").getAsInt()!=1)
                throw new IOException("지원하지 않는 사용자 데이터 형식이에요.");
            return;
        }
        Path legacy=configured("synesis.legacyRoot","SYNESIS_LEGACY_ROOT",appRoot());
        Process migration=process(new ProcessBuilder(PythonRuntime.pdf(),"-B",script("migrate_user_data.py").toString(),
            "--legacy-root",legacy.toString(),"--destination",dataRoot().toString(),"--apply")).inheritIO().start();
        if(migration.waitFor()!=0)throw new IOException("사용자 데이터 이관을 완료하지 못했어요. 기존 데이터는 보존되어 있어요.");
    }
}
