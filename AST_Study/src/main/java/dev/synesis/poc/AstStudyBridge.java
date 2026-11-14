package dev.synesis.poc;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import javax.swing.SwingUtilities;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.concurrent.CompletableFuture;

/** Receives file opens and account shutdown from the Electron main process. */
final class AstStudyBridge {
    private final PrintStream protocolOutput;
    private final CompletableFuture<Void> finished = new CompletableFuture<>();
    private Path documentRoot;
    private LectureWindow window;
    private Long shutdownId;
    private boolean shuttingDown;

    private AstStudyBridge(PrintStream protocolOutput) {
        this.protocolOutput = protocolOutput;
    }

    static void run(String directory) throws Exception {
        PrintStream protocol = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        System.setOut(System.err);
        AstStudyBridge bridge = new AstStudyBridge(protocol);
        Path data;
        try {
            data = Path.of(directory);
            if (!data.isAbsolute()) throw new IOException("Expected an absolute study data directory.");
            data = data.normalize();
            if (data.getParent() == null) throw new IOException("Expected a study data directory inside an AST account.");
            bridge.documentRoot = data.getParent().resolve("focus-library/documents");
            System.setProperty("synesis.appRoot", AppPaths.installedRoot().toString());
            System.setProperty("apple.awt.application.name", "AST Study");
        } catch (Exception failure) {
            bridge.send("error", null, "startup-failed");
            throw failure;
        }

        try (var lock = AstStudyMain.lock(data)) {
            AstStudyMain.prepare(data);
            AppDiagnostics.install();
            SwingUtilities.invokeAndWait(() -> bridge.window = LectureWindow.createStudyWindow(true));
            bridge.window.studyWindowClosed().whenComplete((ignored, failure) -> bridge.complete(failure));
            bridge.send("ready", null, null);
            Thread.startVirtualThread(bridge::readCommands);
            bridge.finished.join();
        } catch (Exception failure) {
            bridge.send("error", null, "startup-failed");
            throw failure;
        }
    }

    private void readCommands() {
        try (var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            for (String line; (line = input.readLine()) != null;) {
                if (!receive(line)) return;
            }
        } catch (IOException failure) {
            AppDiagnostics.error("study.bridge.input", failure, java.util.Map.of());
        }
        SwingUtilities.invokeLater(() -> shutdown(null));
    }

    private boolean receive(String line) {
        Long id = null;
        try {
            if (line.length() > 64 * 1024) throw new IllegalArgumentException();
            JsonObject request = JsonParser.parseString(line).getAsJsonObject();
            id = request.get("id").getAsBigDecimal().longValueExact();
            if (id <= 0 || !request.getAsJsonPrimitive("id").isNumber()) throw new IllegalArgumentException();
            long requestId = id;
            switch (text(request, "command")) {
                case "shutdown" -> {
                    SwingUtilities.invokeLater(() -> shutdown(requestId));
                    return false;
                }
                case "open" -> {
                    Path pdf = Path.of(text(request, "path"));
                    String name = text(request, "name");
                    if (!pdf.isAbsolute() || name.isBlank() || name.length() > 512) throw new IllegalArgumentException();
                    Path managedPdf = managedSource(pdf);
                    if (managedPdf == null) send("error", requestId, "pdf-open-failed");
                    else SwingUtilities.invokeLater(() -> open(requestId, managedPdf, name));
                }
                default -> throw new IllegalArgumentException();
            }
        } catch (RuntimeException malformed) {
            send("error", id, "invalid-request");
        }
        return true;
    }

    private static String text(JsonObject request, String name) {
        var value = request.getAsJsonPrimitive(name);
        if (value == null || !value.isString()) throw new IllegalArgumentException();
        return value.getAsString();
    }

    private Path managedSource(Path pdf) {
        Path normalized = pdf.normalize();
        if (!normalized.startsWith(documentRoot)) return null;
        Path relative = documentRoot.relativize(normalized);
        if (relative.getNameCount() != 2 || !relative.getFileName().toString().equals("source.pdf")
                || !relative.getName(0).toString().matches("[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")) return null;
        try {
            Path account = documentRoot.getParent().getParent();
            Path expected = account.toRealPath().resolve("focus-library/documents").resolve(relative);
            Path actual = normalized.toRealPath();
            return expected.equals(actual) && Files.isRegularFile(actual, LinkOption.NOFOLLOW_LINKS) ? actual : null;
        } catch (IOException missing) {
            return null;
        }
    }

    private void open(long id, Path pdf, String name) {
        if (shuttingDown) {
            send("error", id, "closing");
            return;
        }
        try {
            window.openStudyPdf(pdf, name, code -> {
                if (code == null) send("opened", id, null);
                else send("error", id, code);
            });
        } catch (RuntimeException failure) {
            AppDiagnostics.error("study.bridge.open", failure, java.util.Map.of());
            send("error", id, "pdf-open-failed");
        }
    }

    private void shutdown(Long id) {
        if (shuttingDown) return;
        shuttingDown = true;
        shutdownId = id;
        window.closeWindow();
    }

    private void complete(Throwable failure) {
        if (failure == null) send("closed", shutdownId, null);
        else send("error", shutdownId, "shutdown-failed");
        finished.complete(null);
    }

    private void send(String type, Long id, String code) {
        JsonObject event = new JsonObject();
        event.addProperty("type", type);
        if (id != null) event.addProperty("id", id);
        if (code != null) event.addProperty("code", code);
        protocolOutput.println(event);
    }
}
