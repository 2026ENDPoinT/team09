package dev.synesis.poc;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.synesis.poc.pdf.PdfWorkspace;
import dev.synesis.poc.ui.FloatingMentor;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.font.Standard14Fonts;

import javax.swing.AbstractButton;
import javax.swing.JComboBox;
import javax.swing.JComponent;
import javax.swing.JEditorPane;
import javax.swing.JFrame;
import javax.swing.SwingUtilities;
import javax.swing.text.html.CSS;
import javax.swing.text.html.HTMLDocument;
import java.awt.Component;
import java.awt.Container;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;

/** Exercises the AST study shell with real local PDF preparation in an invisible frame. */
public final class AstStudySmokeTest {
    public static void main(String[] args) throws Exception {
        Path temp = Files.createTempDirectory("ast-study-smoke-").toRealPath();
        try {
            System.setProperty("synesis.appRoot", AppPaths.installedRoot().toString());
            Path data = temp.resolve("study-data");
            AstStudyMain.prepare(data);
            PdfWorkspace.DisplaySettings defaults = PdfWorkspace.displaySettings();
            check(defaults.summaryFont() == 20 && defaults.tutorFont() == 18, "Incorrect default study font sizes");
            Path fontFile = AppPaths.settings().resolve("study-fonts.json");
            Files.createDirectories(fontFile.getParent());
            Files.writeString(fontFile, "{\"summaryFont\":23,\"tutorFont\":19}");
            PdfWorkspace.DisplaySettings saved = PdfWorkspace.displaySettings();
            check(saved.summaryFont() == 23 && saved.tutorFont() == 19, "Study did not read AST's shared font settings");
            Path first = temp.resolve("첫 번째 강의.pdf");
            Path second = temp.resolve("두 번째 강의.pdf");
            writePdf(first, "Acceleration", 2);
            writePdf(second, "Entropy", 3);
            String firstId = digest(first);

            LectureWindow window = onEdt(() -> {
                UiFonts.install();
                return new LectureWindow();
            });
            try {
                PdfWorkspace initial = open(window, first, firstId, 2, "Acceleration", data);
                onEdt(() -> {
                    verifyStudyControls(initial);
                    window.openStudyPdf(first);
                    check(window.studyWorkspace() == initial, "Same document reopened in a new workspace");
                    return null;
                });
                PdfWorkspace next = open(window, second, digest(second), 3, "Entropy", data);
                check(next != initial, "New document inherited another document's workspace");
                open(window, first, firstId, 2, "Acceleration", data);
            } finally {
                onEdt(window::closeWindow).get(45, TimeUnit.SECONDS);
            }
            verifyAutomaticStudy(temp);
        } finally {
            try (var paths = Files.walk(temp)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
        System.out.println("PASS: AST study shell without recording tools, PDF switching, automatic K1.2.5, and cache reuse");
    }

    private static void verifyAutomaticStudy(Path temp) throws Exception {
        Path app = AppPaths.appRoot();
        Path fixtureApp = Files.createDirectory(temp.resolve("automatic-app"));
        Path scripts = Files.createDirectory(fixtureApp.resolve("scripts"));
        Files.createSymbolicLink(fixtureApp.resolve(".venv-pdf"), app.resolve(".venv-pdf"));
        Files.createSymbolicLink(scripts.resolve("pdf_pipeline.py"), app.resolve("scripts/pdf_pipeline.py"));
        Files.writeString(scripts.resolve("pdf_k125_entry.py"), """
            import argparse
            import json
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument('command', choices=['group-plan', 'generate', 'recover'])
            parser.add_argument('--folder', type=Path, required=True)
            parser.add_argument('--request', type=Path, required=True)
            args, _ = parser.parse_known_args()
            request = json.loads(args.request.read_text())
            latest = args.folder / 'generated/newest-k1-2-5/latest-document-0.json'
            if args.command == 'recover':
                result = json.loads(latest.read_text())
            else:
                with (args.folder / 'worker-requests.jsonl').open('a') as log:
                    log.write(json.dumps({'command': args.command, **request}) + '\\n')
                if args.command == 'group-plan':
                    result = {'pendingOriginalUsage': {'requests': 1}}
                else:
                    document = json.loads((args.folder / 'document.json').read_text())
                    result = {'kind': 'ai_generated', 'processingComplete': True, 'coverageComplete': True,
                              'documentId': document['documentId'], 'sourceFingerprint': document['fingerprint'],
                              'strategy': request['strategy'], 'scope': request['scope'], 'page': request['page'],
                              'promptVersion': 'Newest_K1.2.5-v1', 'sections': [], 'concepts': [],
                              'overview': {'title': 'Fixture', 'body': 'Automatic summary fixture'}}
                    latest.parent.mkdir(parents=True, exist_ok=True)
                    latest.write_text(json.dumps(result))
            args.request.with_suffix('.result.json').write_text(json.dumps(result))
            """);
        Path pdf = temp.resolve("자동 해설.pdf");
        writePdf(pdf, "Automatic study", 3);
        String id = digest(pdf);
        Path data = temp.resolve("automatic-data");
        System.setProperty("synesis.appRoot", fixtureApp.toString());
        System.setProperty("ast.study.bridge.invisible", "true");
        AstStudyMain.prepare(data);

        Path oldNotes = Files.createDirectories(data.resolve("recordings/lecture-notes"));
        Path oldNote = oldNotes.resolve("previous.json");
        String oldNoteContents = """
            {"id":"previous","title":"강의록","finished":false,"parts":[]}
            """;
        Files.writeString(oldNote, oldNoteContents);
        generateAutomatically(pdf, id, false);
        generateAutomatically(pdf, id, true);
        check(Files.readString(oldNote).equals(oldNoteContents), "Opening the study window modified a previously saved lecture note");
        try (var files = Files.list(oldNotes)) {
            check(files.toList().equals(List.of(oldNote)), "The study window wrote new lecture notes");
        }
        List<String> requests = Files.readAllLines(data.resolve("library").resolve(id).resolve("worker-requests.jsonl"));
        check(requests.size() == 2, "Expected exactly one planning call and one generation call across all opens: " + requests);
        for (int i = 0; i < requests.size(); i++) {
            JsonObject request = JsonParser.parseString(requests.get(i)).getAsJsonObject();
            check(request.get("command").getAsString().equals(i == 0 ? "group-plan" : "generate"), "Wrong worker call order");
            check(request.get("strategy").getAsString().equals("newest-k1-2-5"), "Wrong automatic study engine");
            check(request.get("scope").getAsString().equals("document") && request.get("page").getAsInt() == 0,
                "Automatic study must cover the full document");
            for (String flag : List.of("retryMissingResponses", "retryUnresolvedResponses")) {
                check(!request.has(flag) || !request.get(flag).getAsBoolean(), "Automatic study enabled " + flag);
            }
        }
        JsonObject plan = JsonParser.parseString(requests.getFirst()).getAsJsonObject();
        check(plan.getAsJsonArray("pages").toString().equals("[1,2,3]"), "Automatic plan omitted pages");
    }

    private static void generateAutomatically(Path pdf, String id, boolean cached) throws Exception {
        LectureWindow window = onEdt(() -> LectureWindow.createStudyWindow(true));
        try {
            CompletableFuture<String> opened = new CompletableFuture<>();
            CompletableFuture<String> reopened = new CompletableFuture<>();
            CompletableFuture<PdfWorkspace.GenerationProgress> finished = new CompletableFuture<>();
            PdfWorkspace workspace = onEdt(() -> {
                window.openStudyPdf(pdf, pdf.getFileName().toString(), opened::complete);
                PdfWorkspace current = window.studyWorkspace();
                current.addPropertyChangeListener(PdfWorkspace.GENERATION_PROGRESS_PROPERTY, event -> {
                    if (event.getNewValue() instanceof PdfWorkspace.GenerationProgress progress && progress.finished())
                        finished.complete(progress);
                });
                window.openStudyPdf(pdf, pdf.getFileName().toString(), reopened::complete);
                check(window.studyWorkspace() == current, "Repeated AST open created a second workspace");
                return current;
            });
            check(opened.get(45, TimeUnit.SECONDS) == null && reopened.get(45, TimeUnit.SECONDS) == null,
                "AST could not open the automatic-study PDF");
            var progress = finished.get(45, TimeUnit.SECONDS);
            check(progress.documentId().equals(id) && progress.percent() == 100 && !progress.failed(),
                "Automatic study did not finish: " + progress);
            check(progress.stage().contains("불러옴") == cached, "Unexpected cache behavior: " + progress.stage());
            onEdt(() -> {
                JFrame frame = frame(workspace);
                check(!frame.isVisible(), "Automatic-study smoke must not display the frame");
                check(!SwingUtilities.isDescendingFrom(workspace.studyActions(), frame.getContentPane()),
                    "The manual generation toolbar is still attached");
                check(find(frame.getContentPane(), AbstractButton.class, button -> "PDF 열기".equals(button.getText())) == null,
                    "The AST study window still has a PDF open button");
                verifyNoRecordingControls(frame.getContentPane());
                require(frame.getContentPane(), JEditorPane.class, pane -> pane.getText().contains("Automatic summary fixture"));
                verifyLearningControls(frame.getContentPane());
                return null;
            });
            if (!cached) {
                Files.createDirectories(AppPaths.settings());
                Files.writeString(AppPaths.settings().resolve("study-fonts.json"), "{\"summaryFont\":26,\"tutorFont\":21}");
                for (int attempt = 0; attempt < 40; attempt++) {
                    boolean updated = onEdt(() -> find(frame(workspace).getContentPane(), JEditorPane.class, pane ->
                        pane.getDocument() instanceof HTMLDocument html && pane.getText().contains("Automatic summary fixture") &&
                            "26pt".equals(String.valueOf(html.getStyleSheet().getRule("body").getAttribute(CSS.Attribute.FONT_SIZE)))) != null);
                    if (updated) return;
                    Thread.sleep(75);
                }
                throw new AssertionError("AST's new font size did not reach the open study window");
            }
        } finally {
            onEdt(window::closeWindow).get(45, TimeUnit.SECONDS);
        }
    }

    private static PdfWorkspace open(LectureWindow window, Path pdf, String id, int pages, String text, Path data)
            throws Exception {
        CompletableFuture<PdfWorkspace.PdfLocation> prepared = new CompletableFuture<>();
        PdfWorkspace workspace = onEdt(() -> {
            window.openStudyPdf(pdf);
            PdfWorkspace current = window.studyWorkspace();
            current.addPropertyChangeListener(PdfWorkspace.PDF_PREPARED_PROPERTY,
                event -> prepared.complete((PdfWorkspace.PdfLocation) event.getNewValue()));
            for (String property : new String[]{PdfWorkspace.PDF_OPEN_FAILED_PROPERTY, PdfWorkspace.PDF_PREPARE_FAILED_PROPERTY}) {
                current.addPropertyChangeListener(property,
                    event -> prepared.completeExceptionally(new AssertionError(event.getNewValue())));
            }
            return current;
        });
        var location = prepared.get(45, TimeUnit.SECONDS);
        check(location.equals(new PdfWorkspace.PdfLocation(id, 1, pages)), "Incorrect document, start page, or page count");
        onEdt(() -> {
            check(pdf.getFileName().toString().equals(workspace.currentPdfName()), "PDF filename was lost");
            check(!frame(workspace).isVisible(), "Smoke must not display the frame");
            check(workspace.generationProgress() == null, "Opening a PDF started generation");
            return null;
        });

        Path stored = data.resolve("library").resolve(id);
        check(Files.mismatch(pdf, stored.resolve("source.pdf")) == -1, "Stored PDF differs from the source");
        JsonObject index = JsonParser.parseString(Files.readString(stored.resolve("document.json"))).getAsJsonObject();
        check(index.getAsJsonArray("pages").get(0).getAsJsonObject().get("nativeText").getAsString().contains(text),
            "PDF text was not extracted");
        check(Files.notExists(stored.resolve("usage")) && Files.notExists(stored.resolve("requests"))
            && Files.notExists(stored.resolve("generated")), "Opening a PDF created a generation request");
        return workspace;
    }

    private static void verifyStudyControls(PdfWorkspace workspace) {
        Container root = frame(workspace).getContentPane();
        button(root, "PDF 열기");
        button(root, "강의 해설");
        button(root, "개념 정리");
        verifyNoRecordingControls(root);
        check(button(root, "PDF 강의 해설·개념 정리 생성").isEnabled(), "Generation is unavailable after local extraction");
        JComboBox<?> strategy = require(root, JComboBox.class, combo -> accessibleName(combo).equals("해설 생성 방식"));
        check(String.valueOf(strategy.getSelectedItem()).startsWith("1.2.5"), "The default generation strategy is not K1.2.5");
        check(find(root, JComponent.class, component -> switch (component.getClass().getSimpleName()) {
            case "PdfLibraryPanel", "HomeAssistant", "LoginPanel" -> true;
            default -> false;
        }) == null, "A SYNESIS home panel is visible in the study shell");

        require(root, AbstractButton.class, control -> "PDF 전체보기".equals(control.getToolTipText())).doClick(0);
        button(root, "돌아가기").doClick(0);
        check(workspace.currentPdfLocation().page() == 1, "Leaving the full PDF view changed the current page");

        verifyLearningControls(root);
        require(root, AbstractButton.class, control -> "화면 설정".equals(control.getToolTipText()));
    }

    private static void verifyLearningControls(Container root) {
        button(root, "AI멘토").doClick(0);
        check(require(root, FloatingMentor.class, mentor -> true).isOpen(), "The mentor button did not open its panel");
        check(require(root, AbstractButton.class, button -> accessibleName(button).equals("질문 보내기")).isEnabled(),
            "The mentor cannot ask about the prepared PDF");
        button(root, "AI멘토").doClick(0);

        button(root, "N제 출제").doClick(0);
        button(root, "문제 생성하기");
    }

    private static void verifyNoRecordingControls(Container root) {
        check(find(root, AbstractButton.class, control -> {
            String name = accessibleName(control);
            return name.contains("강의록") || name.contains("녹음") || "recordingToggle".equals(control.getName());
        }) == null, "A lecture note or recording control is still mounted");
    }

    private static void writePdf(Path path, String topic, int pages) throws Exception {
        try (PDDocument document = new PDDocument()) {
            for (int number = 1; number <= pages; number++) {
                PDPage page = new PDPage();
                document.addPage(page);
                try (var content = new PDPageContentStream(document, page)) {
                    content.beginText();
                    content.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA), 16);
                    content.newLineAtOffset(60, 700);
                    content.showText(topic + ": page " + number);
                    content.endText();
                }
            }
            document.save(path.toFile());
        }
    }

    private static String digest(Path path) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }

    private static JFrame frame(PdfWorkspace workspace) {
        return (JFrame) SwingUtilities.getWindowAncestor(workspace);
    }

    private static AbstractButton button(Container root, String text) {
        AbstractButton control = find(root, AbstractButton.class, button -> text.equals(button.getText()));
        if (control == null) throw new AssertionError("Missing visible button: " + text);
        return control;
    }

    private static String accessibleName(JComponent component) {
        return String.valueOf(component.getAccessibleContext().getAccessibleName());
    }

    private static <T extends Component> T require(Container root, Class<T> type, Predicate<T> condition) {
        T found = find(root, type, condition);
        if (found == null) throw new AssertionError("Missing visible " + type.getSimpleName());
        return found;
    }

    private static <T extends Component> T find(Component component, Class<T> type, Predicate<T> condition) {
        if (!component.isVisible()) return null;
        if (type.isInstance(component) && condition.test(type.cast(component))) return type.cast(component);
        if (component instanceof Container parent) {
            for (Component child : parent.getComponents()) {
                T found = find(child, type, condition);
                if (found != null) return found;
            }
        }
        return null;
    }

    private static <T> T onEdt(Callable<T> task) throws Exception {
        FutureTask<T> future = new FutureTask<>(task);
        SwingUtilities.invokeAndWait(future);
        return future.get();
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
