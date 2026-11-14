package dev.synesis.poc;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Resolves the project's isolated PDF Python environment on Windows and macOS. */
public final class PythonRuntime {
    private PythonRuntime() { }

    public static String pdf() throws IOException {
        Path root = AppPaths.appRoot().resolve(".venv-pdf");
        for (Path candidate : new Path[] {
                root.resolve("bin/python3"), root.resolve("bin/python"),
                root.resolve("Scripts/python.exe") }) {
            if (Files.isRegularFile(candidate)) return candidate.toAbsolutePath().toString();
        }
        throw new IOException("PDF 환경이 없습니다. macOS: ./scripts/setup-mac.sh, Windows: scripts/setup-pdf.ps1");
    }
}
