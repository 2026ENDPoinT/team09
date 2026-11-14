package dev.synesis.poc;

import com.google.gson.Gson;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;

/** Best-effort local diagnostics. Never pass captions, credentials, request bodies or headers here. */
public final class AppDiagnostics {
    private static final Gson JSON = new Gson();
    private static final long START = System.nanoTime();
    private static final long LIMIT = 2 * 1024 * 1024;
    private static Path folder = AppPaths.runtimeState().resolve("logs/diagnostics");
    private static Path file;
    private static boolean installed, warning;
    private AppDiagnostics() { }

    public static Path directory() { return folder; }

    public static synchronized void install() {
        if (installed) return;
        installed = true;
        Thread.setDefaultUncaughtExceptionHandler((thread, failure) ->
                error("uncaught", failure, Map.of("failedThread", thread.getName())));
        Runtime.getRuntime().addShutdownHook(new Thread(() -> event("app.shutdown", Map.of()), "diagnostic-shutdown"));
        event("app.start", Map.of("java", System.getProperty("java.version"),
                "os", System.getProperty("os.name"), "arch", System.getProperty("os.arch"),
                "processors", Runtime.getRuntime().availableProcessors()));
    }

    public static void event(String name, Map<String, ?> fields) { write(name, fields, null); }

    /** Messages/source lines are intentionally omitted: third-party exceptions can contain API keys. */
    public static void error(String stage, Throwable failure, Map<String, ?> fields) {
        write(stage, fields, failure);
    }

    private static synchronized void write(String name, Map<String, ?> fields, Throwable failure) {
        try {
            Files.createDirectories(folder);
            if (file == null) file = folder.resolve("app-" + Instant.now().toString().replace(':', '-')
                    + "-" + ProcessHandle.current().pid() + ".jsonl");
            if (Files.exists(file) && Files.size(file) >= LIMIT) {
                for (int i = 3; i >= 1; i--) {
                    Path source = i == 1 ? file : Path.of(file + "." + (i - 1));
                    if (Files.exists(source)) Files.move(source, Path.of(file + "." + i), StandardCopyOption.REPLACE_EXISTING);
                }
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("at", Instant.now().toString());
            row.put("elapsedMs", (System.nanoTime() - START) / 1_000_000);
            row.put("pid", ProcessHandle.current().pid());
            row.put("thread", Thread.currentThread().getName());
            row.put("event", name);
            row.put("fields", safe(fields));
            if (failure != null) row.put("exception", trace(failure, Collections.newSetFromMap(new IdentityHashMap<>()), 0));
            Files.writeString(file, JSON.toJson(row) + "\n", StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (Exception ignored) {
            if (!warning) { warning = true; System.err.println("Diagnostic log unavailable; application continues."); }
        }
    }

    private static Object safe(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            map.forEach((key, item) -> {
                String name = String.valueOf(key);
                result.put(name, name.toLowerCase(Locale.ROOT).matches(".*(key|token|secret|password|authorization|cookie|transcript|text|prompt|body).*" )
                        ? "[REDACTED]" : safe(item));
            });
            return result;
        }
        if (value == null || value instanceof Number || value instanceof Boolean) return value;
        String text = String.valueOf(value);
        text = text.replaceAll("(?i)Bearer\\s+[^\\s,;]+", "Bearer [REDACTED]")
                .replaceAll("sk-[A-Za-z0-9_-]+", "[REDACTED]");
        return text.substring(0, Math.min(text.length(), 4096));
    }

    private static Object trace(Throwable failure, Set<Throwable> seen, int depth) {
        if (depth >= 8 || !seen.add(failure)) return "truncated-or-cycle";
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("type", failure.getClass().getName());
        result.put("frames", Arrays.stream(failure.getStackTrace()).limit(64).map(StackTraceElement::toString).toList());
        if (failure.getCause() != null) result.put("cause", trace(failure.getCause(), seen, depth + 1));
        result.put("suppressed", Arrays.stream(failure.getSuppressed()).limit(4).map(e -> trace(e, seen, depth + 1)).toList());
        return result;
    }

    static synchronized void testDirectory(Path path) { folder = path; file = null; warning = false; }
}
