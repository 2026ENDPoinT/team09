package dev.synesis.poc;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.UUID;

/** Standalone entry point for the AST PDF study window. */
public final class AstStudyMain {
    private AstStudyMain() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 2 && args[0].equals("--ast-bridge")) {
            AstStudyBridge.run(args[1]);
            // Study workers and the account lock are closed before the bridge returns.
            System.exit(0);
            return;
        }
        if (args.length > 1) throw new IllegalArgumentException("사용법: AST Study [PDF 경로]");
        Path pdf = args.length == 0 ? null : Path.of(args[0]).toAbsolutePath().normalize();
        if (pdf != null && !Files.isRegularFile(pdf)) throw new IOException("열려는 PDF 파일을 찾지 못했어요.");

        Path app = AppPaths.installedRoot();
        System.setProperty("synesis.appRoot", app.toString());
        Path data = app.resolve(".ast-study-data");
        FileChannel lockFile = lock(data);
        try {
            prepare(data);
            AppDiagnostics.install();
            System.setProperty("apple.awt.application.name", "AST Study");
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                try { lockFile.close(); }
                catch (IOException ignored) { /* The process also releases the file lock on exit. */ }
            }, "ast-study-unlock"));
            LectureWindow.openStudy(pdf);
        } catch (Exception failure) {
            lockFile.close();
            throw failure;
        }
    }

    static FileChannel lock(Path data) throws IOException {
        Path runtime = data.resolve(".runtime");
        Files.createDirectories(runtime);
        FileChannel lockFile = FileChannel.open(runtime.resolve("desktop.lock"),
                StandardOpenOption.CREATE, StandardOpenOption.WRITE);
        try {
            if (lockFile.tryLock() != null) return lockFile;
            throw new IOException("AST 학습 창이 이미 열려 있어요. 열린 창에서 PDF를 선택해 주세요.");
        } catch (IOException | RuntimeException failure) {
            lockFile.close();
            throw failure;
        }
    }

    static void prepare(Path data) throws IOException {
        data = data.toAbsolutePath().normalize();
        Files.createDirectories(data);
        Path manifest = data.resolve("manifest.json");
        if (Files.exists(manifest)) {
            JsonObject saved = JsonParser.parseString(Files.readString(manifest)).getAsJsonObject();
            if (!"ast-study".equals(saved.has("application") ? saved.get("application").getAsString() : "")
                    || !"synesis-user-data".equals(saved.has("format") ? saved.get("format").getAsString() : "")
                    || !saved.has("version") || saved.get("version").getAsInt() != 1) {
                throw new IOException("AST 학습 전용 데이터 폴더를 지정해 주세요.");
            }
        } else {
            JsonObject store = new JsonObject();
            store.addProperty("format", "synesis-user-data");
            store.addProperty("version", 1);
            store.addProperty("application", "ast-study");
            store.addProperty("storeId", UUID.randomUUID().toString());
            store.addProperty("createdAtMs", System.currentTimeMillis());
            Path temporary = Files.createTempFile(data, ".manifest-", ".tmp");
            try {
                Files.writeString(temporary, store.toString());
                try { Files.move(temporary, manifest, StandardCopyOption.ATOMIC_MOVE); }
                catch (java.nio.file.AtomicMoveNotSupportedException unsupported) { Files.move(temporary, manifest); }
            } finally {
                Files.deleteIfExists(temporary);
            }
        }
        System.setProperty("synesis.dataRoot", data.toString());
        System.setProperty("synesis.credentialsFile", AppPaths.appRoot().resolve(".env").toString());
        System.setProperty("ast.study.standalone", "true");
    }
}
