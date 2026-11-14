package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.swing.*;
import javax.swing.text.View;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import javax.imageio.ImageIO;

/** The concept article reuses the actual summary skin, without reparsing on resize/disclosure. */
public final class ConceptReadingSkinTest {
    public static void main(String[] args)throws Exception {
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{error.printStackTrace();System.exit(1);});
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("ConceptReadingSkinTest passed: shared typography/table/list/citation views, grouped vector formulas, narrow layout, cached disclosure and untouched stored data.");System.exit(0);
    }
    private static void run()throws Exception {
        Path output=Files.createTempDirectory("synesis-concept-reading-");
        PdfWorkspace workspace=new PdfWorkspace(false,output.resolve("unused-library"));
        try {
            JsonObject result=JsonParser.parseString("""
                {"kind":"ai_generated","strategy":"new-concept-v99","scope":"document","page":0,
                 "concepts":[{"name":"운동량과 보존법칙","pages":[3,8],"entries":[{
                 "definition":"물체의 운동 상태를 나타내는 양이에요.","explanation":"", "easyExplanation":"",
                 "evidence":[{"page":3,"sourceId":"source/3"},{"page":8,"sourceId":"source/8"}],"visualPages":[]}]}]}
                """).getAsJsonObject();
            JsonObject entry=result.getAsJsonArray("concepts").get(0).getAsJsonObject().getAsJsonArray("entries").get(0).getAsJsonObject();
            String markdown="""
                > **핵심 관계식**
                >
                > $$p=mv$$
                >
                > $$p_i=p_f$$
                >
                > 외력이 없을 때 전체 운동량이 보존돼요.

                1. 계를 정해요.
                2. 외력을 확인해요.

                | 항목 | 의미 |
                | --- | --- |
                | 운동량 | 질량과 속도를 곱한 벡터예요. |
                | LongUnbrokenAccountingFinancialStatementToken | 좁은 표에서도 내용이 보여야 해요. |

                > 같은 기준으로 비교해요.

                ```text
                > literal code stays literal
                ```
                """;
            entry.addProperty("explanation",markdown);
            entry.addProperty("easyExplanation","> $$p=mv$$\n\n| 비교 | 뜻 |\n|---|---|\n| 무거운 공 | 더 큰 운동량 |\n");
            String original=result.toString();set(workspace,"generated",result);
            ((JSlider)get(workspace,"conceptFontSize")).setValue(16);
            Method show=PdfWorkspace.class.getDeclaredMethod("showConcepts");show.setAccessible(true);show.invoke(workspace);
            JPanel list=(JPanel)get(workspace,"conceptList");
            JButton toggle=button(list,"운동량과 보존법칙");toggle.doClick(0);
            layout(list,648);button(list,"쉬운 설명 보기").doClick(0);layout(list,648);
            List<StudyHtmlPane> panes=editors(list);List<SummaryFormulaGroup> formulas=groups(list);
            require(formulas.size()>=2,"core/easy formula groups missing");
            Map<String,Integer> counts=new HashMap<>();
            for(StudyHtmlPane pane:panes)views(pane.getUI().getRootView(pane),counts);
            require(counts.getOrDefault("MathView",0)==3,"grouping lost vector formulas");
            require(counts.getOrDefault("NumberedListView",0)==1,"numbered-list skin missing");
            require(counts.getOrDefault("CardView",0)>0&&counts.getOrDefault("CitationView",0)>0,"quote/source-chip skin missing");
            require(panes.stream().anyMatch(p->p.getText().contains("study-table")),"table skin missing");
            Method document=PdfWorkspace.class.getDeclaredMethod("conceptDocumentHtml",String.class,int.class);document.setAccessible(true);
            String body=StudyMarkdown.render(markdown,16);
            require(document.invoke(null,body,16).equals(SummarySkin.formulaDocument(body,16)),"concept styles diverged from shared summary CSS");
            long[] revisions=panes.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
            snapshot(list,output.resolve("wide.png"));
            layout(list,340);snapshot(list,output.resolve("narrow.png"));
            require(horizontalRange(list),"oversized table/code has no horizontal viewport");
            for(StudyHtmlPane pane:panes){
                var last=pane.modelToView2D(pane.getDocument().getLength());
                require(last==null||last.getMaxY()<=pane.getHeight()+2,"narrow layout clipped text");
            }
            button(list,"쉬운 설명 접기").doClick(0);button(list,"쉬운 설명 보기").doClick(0);
            toggle.doClick(0);toggle.doClick(0);layout(list,648);
            require(editors(list).equals(panes)&&groups(list).equals(formulas),"disclosure rebuilt cached components");
            for(int i=0;i<panes.size();i++)require(panes.get(i).contentRevision()==revisions[i],"resize/disclosure reparsed HTML");
            require(result.toString().equals(original),"skin mutated saved concept data");
            System.out.println("Offscreen previews: "+output);
        }finally{workspace.close();}
    }
    private static void layout(Container root,int width){root.setSize(width,Math.max(1,root.getPreferredSize().height));for(int i=0;i<8;i++){tree(root);root.setSize(width,Math.max(1,root.getPreferredSize().height));}}
    private static void tree(Container c){c.invalidate();c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)tree(nested);}
    private static void snapshot(JComponent c,Path p)throws Exception{BufferedImage i=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=i.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,i.getWidth(),i.getHeight());c.printAll(g);g.dispose();ImageIO.write(i,"png",p.toFile());}
    private static JButton button(Container c,String label){for(Component child:c.getComponents()){if(child instanceof JButton b&&(label.equals(b.getText())||label.equals(b.getAccessibleContext().getAccessibleName())))return b;if(child instanceof Container nested){JButton found=button(nested,label);if(found!=null)return found;}}return null;}
    private static List<StudyHtmlPane> editors(Container c){List<StudyHtmlPane> result=new ArrayList<>();for(Component child:c.getComponents()){if(child instanceof StudyHtmlPane pane)result.add(pane);else if(child instanceof Container nested)result.addAll(editors(nested));}return result;}
    private static List<SummaryFormulaGroup> groups(Container c){List<SummaryFormulaGroup> result=new ArrayList<>();for(Component child:c.getComponents()){if(child instanceof SummaryFormulaGroup group)result.add(group);else if(child instanceof Container nested)result.addAll(groups(nested));}return result;}
    private static boolean horizontalRange(Container c){for(Component child:c.getComponents()){if(child instanceof JScrollPane scroll&&scroll.getHorizontalScrollBar().getMaximum()>scroll.getHorizontalScrollBar().getVisibleAmount())return true;if(child instanceof Container nested&&horizontalRange(nested))return true;}return false;}
    private static void views(View view,Map<String,Integer> counts){counts.merge(view.getClass().getSimpleName(),1,Integer::sum);for(int i=0;i<view.getViewCount();i++)views(view.getView(i),counts);}
    private static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
