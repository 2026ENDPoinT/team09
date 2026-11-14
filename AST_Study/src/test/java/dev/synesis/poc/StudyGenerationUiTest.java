package dev.synesis.poc;

import dev.synesis.poc.pdf.PdfWorkspace;

import javax.swing.JButton;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import java.nio.file.Files;
import java.util.Comparator;
import java.util.Locale;
import java.util.concurrent.Callable;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Verifies document switching during generation in an invisible study window. */
public final class StudyGenerationUiTest {
    public static void main(String[] args) throws Exception {
        var data = Files.createTempDirectory("ast-study-generation-ui-");
        try {
            AstStudyMain.prepare(data);
            LectureWindow window = onEdt(() -> {
                UiFonts.install();
                return new LectureWindow();
            });
            try {
                onEdt(() -> {
                    verifyBackgroundGeneration(window);
                    return null;
                });
            } finally {
                onEdt(window::closeWindow).get(45, TimeUnit.SECONDS);
            }
        } finally {
            try (var paths = Files.walk(data)) {
                for (var path : paths.sorted(Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
        System.out.println("PASS: background summary generation and document switching");
    }

    private static void verifyBackgroundGeneration(LectureWindow window) throws Exception {
        if (System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("mac")
                && field(window, "macFullscreenListener") == null)
            throw new AssertionError("macOS fullscreen transition listener was not installed");
        JPanel root = (JPanel) field(window, "root");
        PdfWorkspace first = window.studyWorkspace();
        if (!SwingUtilities.isDescendingFrom(first, root) || !SwingUtilities.isDescendingFrom(first.studyActions(), root))
            throw new AssertionError("PDF workspace and generation controls must be mounted at startup");

        var setProgress = PdfWorkspace.class.getDeclaredMethod("setGenerationProgress", PdfWorkspace.GenerationProgress.class);
        setProgress.setAccessible(true);
        setProgress.invoke(first, new PdfWorkspace.GenerationProgress("sample", "강의자료.pdf", 42, "해설 생성 중", false, false));
        PdfWorkspace.GenerationProgress displayed = first.generationProgress();
        var switchWorkspace = LectureWindow.class.getDeclaredMethod("switchWorkspace", PdfWorkspace.class);
        switchWorkspace.setAccessible(true);
        PdfWorkspace second = new PdfWorkspace(false);
        switchWorkspace.invoke(window, second);
        JButton background = (JButton) field(window, "backgroundButton");
        if (!background.isVisible() || !displayed.equals(first.generationProgress()))
            throw new AssertionError("Document switching cancelled or hid a running generation");
        if (!SwingUtilities.isDescendingFrom(second.studyActions(), root) || SwingUtilities.isDescendingFrom(first.studyActions(), root))
            throw new AssertionError("Actions did not switch to the active workspace");

        var reopen = LectureWindow.class.getDeclaredMethod("showBackgroundWorkspace", PdfWorkspace.class);
        reopen.setAccessible(true);
        reopen.invoke(window, first);
        if (window.studyWorkspace() != first || !displayed.equals(first.generationProgress()) || background.isVisible())
            throw new AssertionError("Reopening the background document lost generation state");
    }

    private static Object field(Object target, String name) throws Exception {
        var field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
    }

    private static <T> T onEdt(Callable<T> task) throws Exception {
        FutureTask<T> future = new FutureTask<>(task);
        SwingUtilities.invokeAndWait(future);
        return future.get();
    }
}
