package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;

/** Raw PDF glyphs must not be parsed or laid out behind the active PDF canvas. */
public final class PdfInactiveOriginalTest {
    public static void main(String[] args) throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        Path root=Files.createTempDirectory("synesis-inactive-original-");
        Path pdf=root.resolve("fixture.pdf");
        try(PDDocument document=new PDDocument()) {
            document.addPage(new PDPage());document.addPage(new PDPage());document.save(pdf.toFile());
        }
        try(PdfSource source=PdfSource.open(pdf,root.resolve("library"))) {
            SwingUtilities.invokeAndWait(()->{
                PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("library"));
                try {check(workspace,source);}catch(Exception error){throw new RuntimeException(error);}
                finally {workspace.close();}
            });
        }
        System.out.println("PdfInactiveOriginalTest: hidden parsing/layout skipped; latest page, index updates, document reuse, search and resize timer passed");
        System.exit(0);
    }

    private static void check(PdfWorkspace workspace,PdfSource source) throws Exception {
        field("source").set(workspace,source);
        JsonObject index=JsonParser.parseString("""
            {"pages":[{"label":"1","number":1,"nativeText":"첫 원문 𝑑 𝒗 𝐹","status":"ready"},
                      {"label":"2","number":2,"nativeText":"둘째 원문 𝑑 𝒗 𝐹","status":"ready"}]}
            """).getAsJsonObject();
        field("index").set(workspace,index);
        ((JSpinner)field("pageNumber").get(workspace)).setModel(new SpinnerNumberModel(1,1,2,1));
        JTabbedPane tabs=(JTabbedPane)field("sourceTabs").get(workspace);
        JEditorPane original=(JEditorPane)field("original").get(workspace);
        JScrollPane scroll=(JScrollPane)tabs.getComponentAt(1);
        int[] edits={0};
        original.getDocument().addDocumentListener(new javax.swing.event.DocumentListener() {
            public void insertUpdate(javax.swing.event.DocumentEvent event){edits[0]++;}
            public void removeUpdate(javax.swing.event.DocumentEvent event){edits[0]++;}
            public void changedUpdate(javax.swing.event.DocumentEvent event){edits[0]++;}
        });
        Object emptyDocument=original.getDocument();
        call(workspace,"updateOriginal");
        require(edits[0]==0,"hidden update reparsed raw PDF glyphs");
        require(original.getDocument()==emptyDocument,"hidden update parsed a raw PDF document");
        require(original.getDocument().getLength()==0,"hidden update materialized raw text");
        require(scroll.getViewport().getView()==null,"hidden raw text remains in the layout tree");

        tabs.setSelectedIndex(1);
        require(scroll.getViewport().getView()==original,"original tab did not attach its text view");
        require(text(original).contains("첫 원문"),"original tab did not display the latest page");
        Object firstDocument=original.getDocument();
        int openedEdits=edits[0];
        original.select(2,6);
        tabs.setSelectedIndex(0);tabs.setSelectedIndex(1);
        require(edits[0]==openedEdits,"unchanged tab switch reparsed raw PDF glyphs");
        require(original.getDocument()==firstDocument && original.getSelectionStart()==2 && original.getSelectionEnd()==6,
            "unchanged tab switch reparsed the document or lost selection");

        tabs.setSelectedIndex(0);
        field("page").setInt(workspace,2);
        call(workspace,"updateOriginal");
        require(edits[0]==openedEdits,"hidden page change reparsed raw PDF glyphs");
        require(original.getDocument()==firstDocument && text(original).contains("첫 원문"),
            "hidden page change reparsed raw glyphs");
        tabs.setSelectedIndex(1);
        require(text(original).contains("둘째 원문") && !text(original).contains("첫 원문"),"original tab showed a stale page");
        tabs.setSelectedIndex(0);
        index.getAsJsonArray("pages").get(1).getAsJsonObject().addProperty("nativeText","갱신된 원문");
        call(workspace,"updateOriginal");tabs.setSelectedIndex(1);
        require(text(original).contains("갱신된 원문"),"updated extraction was not shown");

        tabs.setSelectedIndex(0);
        @SuppressWarnings("unchecked") DefaultListModel<JsonObject> items=(DefaultListModel<JsonObject>)field("searchItems").get(workspace);
        items.addElement(JsonParser.parseString("{\"page\":2,\"source\":\"native\",\"text\":\"찾은 원문 구절\"}").getAsJsonObject());
        ((JList<?>)field("searchResults").get(workspace)).setSelectedIndex(0);
        require(tabs.getSelectedIndex()==1 && text(original).contains("찾은 원문 구절"),"lazy tab activation overwrote the search result");

        tabs.setSelectedIndex(0);
        Timer timer=(Timer)field("scrollPageTimer").get(workspace);
        timer.start();
        Method preview=PdfWorkspace.class.getDeclaredMethod("previewPdfResize",Class.forName("dev.synesis.poc.pdf.PdfWorkspace$ZoomAnchor"));
        preview.setAccessible(true);preview.invoke(workspace,new Object[]{null});
        require(!timer.isRunning(),"resize left page tracking queued");
        call(workspace,"onPageViewportChanged");
        require(!timer.isRunning(),"resize restarted page tracking before layout settled");
    }
    private static Field field(String name) throws Exception {
        Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field;
    }
    private static void call(PdfWorkspace workspace,String name) throws Exception {
        Method method=PdfWorkspace.class.getDeclaredMethod(name);method.setAccessible(true);method.invoke(workspace);
    }
    private static String text(JEditorPane pane) throws Exception {
        return pane.getDocument().getText(0,pane.getDocument().getLength());
    }
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
}
