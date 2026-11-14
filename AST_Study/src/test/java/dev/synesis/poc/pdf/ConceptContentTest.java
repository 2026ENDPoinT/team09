package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.List;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.Path;
import javax.swing.*;

/** Offline role grouping and preservation of differing conditions/citations. */
public final class ConceptContentTest {
    public static void main(String[] args) throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        JsonArray entries=JsonParser.parseString("""
            [{"definition":"같은 정의","explanation":"조건 x > 0","evidence":[{"page":1}],"visualPages":[1]},
             {"definition":"같은 정의","explanation":"조건 x < 0","evidence":[{"page":2}],"visualPages":[2],"standardKnowledgeUsed":true}]
            """).getAsJsonArray();
        String original=entries.toString();
        List<ConceptContent.Row> rows=ConceptContent.rows(entries,"definition","explanation");
        require(rows.size()==3,"different conditions were removed or exact definition repeated");
        require(rows.get(0).field().equals("definition") && rows.get(1).field().equals("explanation")
            && rows.get(2).field().equals("explanation"),"roles must be grouped in reading order");
        require(rows.get(0).entry().getAsJsonArray("evidence").size()==2,"deduplication lost citations");
        require(rows.get(0).entry().getAsJsonArray("visualPages").size()==2,"deduplication lost source pages");
        require(rows.get(0).entry().get("standardKnowledgeUsed").getAsBoolean(),"knowledge flag was lost");
        require(entries.toString().equals(original),"display mutated saved entries");
        SwingUtilities.invokeAndWait(()->{
            try {checkWorkspace(entries);}catch(Exception error){throw new RuntimeException(error);}
        });
        entries.get(1).getAsJsonObject().add("stepFlow",new JsonObject());
        require(ConceptContent.rows(entries,"definition").size()==2,"distinct interactive module was dropped");
        System.out.println("ConceptContentTest: role ordering, citations, conditions, modules and Swing headings preserved");
        System.exit(0);
    }
    private static void checkWorkspace(JsonArray entries) throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-unused-concept-fixture"));
        try {
            JsonObject result=JsonParser.parseString("""
                {"kind":"ai_generated","strategy":"new-concept-v99","scope":"document","page":0,
                 "concepts":[{"name":"검사 개념","pages":[1,2],"entries":[]}]}
                """).getAsJsonObject();
            result.getAsJsonArray("concepts").get(0).getAsJsonObject().add("entries",entries.deepCopy());
            Field generated=PdfWorkspace.class.getDeclaredField("generated");generated.setAccessible(true);generated.set(workspace,result);
            Method show=PdfWorkspace.class.getDeclaredMethod("showConcepts");show.setAccessible(true);show.invoke(workspace);
            Field list=PdfWorkspace.class.getDeclaredField("conceptList");list.setAccessible(true);
            require(allHtml((Container)list.get(workspace)).isEmpty(),"initial concept body must stay collapsed and lazy");
            expand((Container)list.get(workspace),"검사 개념");
            String html=allHtml((Container)list.get(workspace));
            java.nio.file.Files.writeString(Path.of("build/concept-quality-20261016/concept-fixture.html"),html);
            html=java.util.regex.Pattern.compile("&#(\\d+);").matcher(html)
                .replaceAll(match->Character.toString(Integer.parseInt(match.group(1))));
            require(html.split("<h4>",-1).length-1==2,"Swing repeated the role headings");
            var headings=java.util.regex.Pattern.compile("<h4>\\s*([^<]+)").matcher(html);
            require(headings.find() && headings.group(1).strip().equals("정의"),"Swing changed first role");
            require(headings.find() && headings.group(1).strip().equals("설명"),"Swing changed second role");
            require(html.contains("x &gt; 0") && html.contains("x &lt; 0"),"Swing lost differing conditions");
        } finally {workspace.close();}
    }
    private static String allHtml(Container container) {
        StringBuilder text=new StringBuilder();
        for(Component component:container.getComponents()) {
            if(component instanceof JEditorPane pane)text.append(pane.getText());
            else if(component instanceof Container nested)text.append(allHtml(nested));
        }
        return text.toString();
    }
    private static boolean expand(Container container,String name) {
        for(Component component:container.getComponents()) {
            if(component instanceof JButton button&&name.equals(button.getAccessibleContext().getAccessibleName())){button.doClick();return true;}
            if(component instanceof Container nested&&expand(nested,name))return true;
        }
        return false;
    }
    private static void require(boolean condition,String message) {
        if(!condition)throw new AssertionError(message);
    }
}
