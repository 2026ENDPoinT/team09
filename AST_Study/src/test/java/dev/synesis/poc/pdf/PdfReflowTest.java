package dev.synesis.poc.pdf;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.common.PDRectangle;

import javax.swing.*;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;

/** Checks PDF position across recording-panel and window-size layout changes, offline. */
public final class PdfReflowTest {
    public static void main(String[] args) throws Exception {
        Path folder=Files.createTempDirectory("synesis-pdf-reflow-");
        Path pdf=folder.resolve("three-pages.pdf");
        try(PDDocument document=new PDDocument()) {
            for(int i=0;i<3;i++)document.addPage(new PDPage(PDRectangle.A4));
            document.save(pdf.toFile());
        }
        try(PdfSource source=PdfSource.open(pdf,folder.resolve("library"))) {
            PdfWorkspace workspace=new PdfWorkspace(false,folder.resolve("library"));
            try {
                SwingUtilities.invokeAndWait(()->{
                    try {
                        workspace.setSize(1240,760);
                        Field sourceField=PdfWorkspace.class.getDeclaredField("source");
                        sourceField.setAccessible(true);
                        sourceField.set(workspace,source);
                        ((JSpinner)PdfSmokeTest.field(workspace,"pageNumber"))
                            .setModel(new SpinnerNumberModel(1,1,3,1));
                        PdfSmokeTest.layout(workspace);
                        Method render=PdfWorkspace.class.getDeclaredMethod("renderPage");
                        render.setAccessible(true);
                        render.invoke(workspace);
                    } catch(Exception error) {throw new RuntimeException(error);}
                });
                SwingUtilities.invokeAndWait(()->{});
                PdfSmokeTest.checkPdfReflow(workspace);
                System.out.println("PASS: PDF position survives recording panel and window resize");
            } finally {workspace.close();}
        }
    }
}
