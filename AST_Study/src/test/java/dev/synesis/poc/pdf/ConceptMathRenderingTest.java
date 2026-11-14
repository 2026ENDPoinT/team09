package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.imageio.ImageIO;
import javax.swing.*;
import javax.swing.text.View;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.Map;
import java.util.regex.Pattern;

/** Offline check of actual concept/summary Swing composition, including wide equations. */
public final class ConceptMathRenderingTest {
    private static final String MOMENTUM = "\\(m_1v_{1i}+m_2v_{2i}=m_1v_{1f}+m_2v_{2f}\\)";
    private static final Pattern SCROLL = Pattern.compile("<!--MATHSCROLL:");
    private static final Pattern INLINE = Pattern.compile("<math ");

    public static void main(String[] args) throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        JsonObject concept;
        if(args.length>0) {
            JsonObject saved=JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject();
            concept=null;
            for(JsonElement item:saved.getAsJsonArray("concepts"))
                if(item.getAsJsonObject().get("name").getAsString().startsWith("일차원 탄성 충돌의"))
                    concept=item.getAsJsonObject().deepCopy();
            require(concept!=null,"elastic collision concept was not found");
        } else {
            concept=JsonParser.parseString("""
                {"name":"일차원 탄성 충돌의 운동량 보존","pages":[9,10],
                 "entries":[{"definition":"탄성 충돌에서는 운동량과 운동 에너지가 보존돼요.",
                  "explanation":"","easyExplanation":"","evidence":[],"visualPages":[]}]}
                """).getAsJsonObject();
            concept.getAsJsonArray("entries").get(0).getAsJsonObject().addProperty("explanation",
                "질량은 \\(m_1,m_2\\)예요. 운동량 보존은 "+MOMENTUM+"예요.\n\n"
                +"운동 에너지 보존은 \\(\\frac{1}{2}m_1v_{1i}^2+\\frac{1}{2}m_2v_{2i}^2="
                +"\\frac{1}{2}m_1v_{1f}^2+\\frac{1}{2}m_2v_{2f}^2\\)예요.");
        }
        // Exercise easy explanations too, without changing the saved source.
        JsonObject entry=concept.getAsJsonArray("entries").get(0).getAsJsonObject();
        entry.addProperty("easyExplanation","충돌 전후 운동량은 같아요.\n\n"+MOMENTUM+"\n\n이 관계를 함께 풀어요.");
        JsonObject fixture=JsonParser.parseString("""
            {"kind":"ai_generated","strategy":"new-concept-v99","scope":"document","page":0,"concepts":[]}
            """).getAsJsonObject();
        fixture.getAsJsonArray("concepts").add(concept);
        SwingUtilities.invokeAndWait(()->{
            try {checkWorkspace(fixture);}catch(Exception error){throw new RuntimeException(error);}
        });
        System.exit(0);
    }

    private static void checkWorkspace(JsonObject fixture) throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-unused-concept-math"));
        try {
            field("generated").set(workspace,fixture);
            Method show=PdfWorkspace.class.getDeclaredMethod("showConcepts");show.setAccessible(true);show.invoke(workspace);
            JPanel list=(JPanel)field("conceptList").get(workspace);
            String conceptName=fixture.getAsJsonArray("concepts").get(0).getAsJsonObject().get("name").getAsString();
            conceptButton(list,conceptName).doClick();
            button(list,"쉬운 설명 보기").doClick();

            int expectedScroll=0,expectedInline=0;
            StringBuilder summaryBody=new StringBuilder();
            for(JsonElement item:fixture.getAsJsonArray("concepts").get(0).getAsJsonObject().getAsJsonArray("entries")) {
                for(String name:new String[]{"definition","explanation","easyExplanation"}) {
                    String rendered=StudyMarkdown.renderWithScrollableMath(item.getAsJsonObject().get(name).getAsString(),16);
                    expectedScroll+=(int)SCROLL.matcher(rendered).results().count();
                    expectedInline+=(int)INLINE.matcher(rendered).results().count();
                    summaryBody.append(rendered);
                }
            }
            require(expectedScroll>=2,"fixture must contain wide equations in both the body and easy explanation");
            Method summary=PdfWorkspace.class.getDeclaredMethod("renderSummaryContent",String.class,Map.class);
            summary.setAccessible(true);summary.invoke(workspace,summaryBody.toString(),Map.of());
            JPanel summaryFlow=(JPanel)field("summaryFlow").get(workspace);
            int conceptScroll=countScroll(list),summaryScroll=countScroll(summaryFlow);
            require(conceptScroll==expectedScroll,"concept lost wide equations: "+conceptScroll+" / "+expectedScroll);
            require(summaryScroll==conceptScroll,"concept and summary must use the same math rows");

            layoutTree(list,960);
            int vectors=countVectors(list);
            require(vectors==expectedScroll+expectedInline,
                "some equations have no vector view: "+vectors+" / "+(expectedScroll+expectedInline));
            for(JEditorPane pane:editors(list)) {
                require(!pane.getText().contains("MATHSCROLL:"),"unmaterialized formula marker");
                String text=pane.getDocument().getText(0,pane.getDocument().getLength());
                require(!text.contains("\\("),"raw TeX delimiter shown to learner");
            }
            int height=list.getPreferredSize().height;
            list.setSize(960,height);layoutTree(list,960);
            BufferedImage image=new BufferedImage(960,height,BufferedImage.TYPE_INT_RGB);
            Graphics2D graphics=image.createGraphics();graphics.setColor(Color.WHITE);graphics.fillRect(0,0,960,height);
            list.printAll(graphics);graphics.dispose();
            Path output=Path.of("build/pdf-tests/concept-elastic-collision-math.png");
            Files.createDirectories(output.getParent());ImageIO.write(image,"png",output.toFile());
            layoutTree(list,320);
            require(countVectors(list)==vectors,"narrow layout dropped equations");
            require(hasHorizontalRange(list),"narrow layout cannot scroll wide equations");
            System.out.println("ConceptMathRenderingTest: "+vectors+" equations visible, "+conceptScroll
                +" shared summary math rows; easy explanation, narrow scrolling and raw TeX checks passed; "+output);
        } finally {workspace.close();}
    }

    private static Field field(String name) throws Exception {
        Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field;
    }
    private static JButton button(Container container,String prefix) {
        for(Component child:container.getComponents()) {
            if(child instanceof JButton button && button.getText()!=null && button.getText().contains(prefix))return button;
            if(child instanceof Container nested) {JButton found=button(nested,prefix);if(found!=null)return found;}
        }
        return null;
    }
    private static JButton conceptButton(Container container,String name) {
        for(Component child:container.getComponents()) {
            if(child instanceof JButton button&&name.equals(button.getAccessibleContext().getAccessibleName()))return button;
            if(child instanceof Container nested){JButton found=conceptButton(nested,name);if(found!=null)return found;}
        }
        return null;
    }
    private static java.util.List<JEditorPane> editors(Container container) {
        var panes=new java.util.ArrayList<JEditorPane>();
        for(Component child:container.getComponents())
            if(child instanceof JEditorPane pane)panes.add(pane);
            else if(child instanceof Container nested)panes.addAll(editors(nested));
        return panes;
    }
    private static int countScroll(Container container) {
        int count=0;
        for(Component child:container.getComponents()) {
            if((child.getClass().getSimpleName().equals("MathScrollPane") || child instanceof SummaryFormulaGroup))count++;
            if(child instanceof Container nested)count+=countScroll(nested);
        }
        return count;
    }
    private static int countVectors(Container container) {
        return editors(container).stream().mapToInt(pane->countVectors(pane.getUI().getRootView(pane))).sum();
    }
    private static int countVectors(View view) {
        int count=view.getClass().getSimpleName().equals("MathView")?1:0;
        for(int i=0;i<view.getViewCount();i++)count+=countVectors(view.getView(i));
        return count;
    }
    private static boolean hasHorizontalRange(Container container) {
        for(Component child:container.getComponents()) {
            if(child instanceof JScrollPane scroll
                && scroll.getHorizontalScrollBar().getMaximum()>scroll.getHorizontalScrollBar().getVisibleAmount())return true;
            if(child instanceof Container nested && hasHorizontalRange(nested))return true;
        }
        return false;
    }
    private static void layoutTree(Container container,int width) {
        container.setSize(width,Math.max(1,container.getPreferredSize().height));container.doLayout();
        for(Component child:container.getComponents())
            if(child instanceof Container nested && child.isVisible()) {
                nested.doLayout();
                if(!(child instanceof JEditorPane))layoutTree(nested,Math.max(1,nested.getWidth()));
            }
    }
    private static void require(boolean condition,String message) {
        if(!condition)throw new AssertionError(message);
    }
}
