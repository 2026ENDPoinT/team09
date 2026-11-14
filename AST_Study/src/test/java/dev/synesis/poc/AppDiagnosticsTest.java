package dev.synesis.poc;

import java.nio.file.*;
import java.util.Map;

public final class AppDiagnosticsTest {
    public static void main(String[] args) throws Exception {
        Path folder = Files.createTempDirectory("synesis-diagnostics-test-");
        AppDiagnostics.testDirectory(folder);
        AppDiagnostics.install();
        RuntimeException failure = new RuntimeException("secret-random-value", new IllegalStateException("private-caption"));
        failure.addSuppressed(new IllegalArgumentException("another-secret"));
        AppDiagnostics.error("test.failure", failure, Map.of("apiKey", "hidden-key", "session", "fixture", "detail", "Bearer abcdef sk-abcdef"));
        Thread uncaught = new Thread(() -> { throw new IllegalStateException("uncaught-secret"); }, "test-uncaught");
        uncaught.start(); uncaught.join();
        StringBuilder all = new StringBuilder();
        try (var paths = Files.list(folder)) {
            for (Path path : paths.toList()) all.append(Files.readString(path));
        }
        for (String secret : new String[]{"secret-random-value", "private-caption", "another-secret", "hidden-key", "abcdef", "uncaught-secret"})
            if (all.toString().contains(secret)) throw new AssertionError("Secret leaked");
        if (!all.toString().contains("test.failure") || !all.toString().contains("uncaught")
                || !all.toString().contains("AppDiagnosticsTest.java") || !all.toString().contains("suppressed"))
            throw new AssertionError("Missing diagnostics");
        for (int i = 0; i < 2500; i++) AppDiagnostics.event("rotation", Map.of("detail", "x".repeat(4000)));
        try (var paths = Files.list(folder)) {
            var files = paths.toList();
            if (files.size() != 4) throw new AssertionError("Rotation not bounded: " + files.size());
            for (Path path : files) if (Files.size(path) > 2 * 1024 * 1024 + 8192) throw new AssertionError("Oversize log");
        }
        Path blocked = Files.createTempFile("synesis-log-blocked-", ".file");
        AppDiagnostics.testDirectory(blocked);
        AppDiagnostics.error("unwritable", failure, Map.of()); // must not throw
        AppDiagnostics.testDirectory(folder);
        System.out.println("PASS: metadata, exception chains, uncaught errors, redaction, rotation, unavailable disk");
    }
}
