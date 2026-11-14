package dev.synesis.poc.pdf;

import javax.swing.*;
import javax.swing.text.GlyphView;
import javax.swing.text.View;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.List;

/** Offline regressions for saved pointer questions, Markdown code, and native vector math. */
public final class QuizRichTextTest {
    private static final String CODE="int a[3] = {4, 7, 10}; int *p = a;";
    private static final String STEM="`"+CODE+"`라고 하자. `*a`와 `*p`가 가리키는 값이 같은 이유를 설명하고, 배열 이름과 포인터가 완전히 같은 것은 아닌 이유를 서술하시오.";
    private static int checks;
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});
        System.out.println("QuizRichTextTest passed: "+checks+" checks; code source, local scroll, pointer labels, vector equations, all question sections, and cached resize. No app windows or API calls.");
        System.exit(0);
    }
    private static void run()throws Exception {
        String prepared=QuizRichText.blockCodeStatements(STEM);
        require(prepared.contains("```\n"+CODE+"\n```"),"saved inline statement did not become a code block");
        require(prepared.contains("`*a`와 `*p`"),"short pointers were changed");
        require(QuizRichText.blockCodeStatements("값은 `a[0]`와 `*p`예요.").equals("값은 `a[0]`와 `*p`예요."),"short code was lifted");
        String fenced="```c\nif (a < b && b > 0) {\n    printf(\"$x$ \\\\frac{1}{2}\");\n}\n```";
        require(QuizRichText.blockCodeStatements(fenced).equals(fenced),"fenced code was rewritten");
        String table="|코드|뜻|\n|---|---|\n|`"+CODE+"`|선언|";
        require(QuizRichText.blockCodeStatements(table).equals(table),"code promotion broke a table cell");
        QuizRichText stem=new QuizRichText(STEM,18,Color.WHITE,true,QuizPlayDesign.TEXT);
        require(stem.getComponentCount()==2,"statement and prose need separate native viewports");
        require("quiz-code-block".equals(stem.getComponent(0).getName()),"code block missing");
        require(text(stem.textPanes().getFirst()).contains(CODE),"array/pointer source was altered");
        require(text(stem.textPanes().get(1)).contains("*a와 *p"),"inline pointer text was lost");
        QuizRichText code=new QuizRichText(fenced,16);
        StudyHtmlPane codePane=code.textPanes().getFirst();
        String literal=text(codePane);
        require(literal.contains("a < b && b > 0")&&literal.contains("    printf"),"code symbols/indentation were lost");
        require(literal.contains("$x$")&&literal.contains("\\frac{1}{2}"),"math inside code was interpreted");
        QuizRichText math=new QuizRichText("식 $\\frac{a}{b}$를 비교해요.\n\n$$\\sum_{i=1}^{n} x_i^2=\\int_0^1 f(x)\\,dx$$\n\n다음 설명은 정상적으로 줄바꿈돼요.",16);
        require(math.getComponentCount()==3,"display equation was not isolated from prose");
        List<javax.swing.text.Document> documents=stem.textPanes().stream().map(JEditorPane::getDocument).toList();
        for(int width:new int[]{640,320,900,400,640}) {
            for(QuizRichText content:List.of(stem,code,math)) {
                layoutAt(content,width);
                BufferedImage rendered=new BufferedImage(width,Math.max(1,content.getHeight()),BufferedImage.TYPE_INT_RGB);
                Graphics2D graphics=rendered.createGraphics();graphics.setColor(Color.WHITE);graphics.fillRect(0,0,rendered.getWidth(),rendered.getHeight());content.paint(graphics);graphics.dispose();
                int bottom=0;
                for(Component child:content.getComponents()) {
                    require(child.getY()>=bottom,"blocks overlap after resize");bottom=child.getY()+child.getHeight();
                    require(bottom<=content.getHeight(),"block exceeds the card height");
                }
            }
            require(stem.textPanes().stream().map(JEditorPane::getDocument).toList().equals(documents),"resize rebuilt HTML documents");
            JScrollPane codeScroll=scroll(stem.textPanes().getFirst());
            JScrollPane proseScroll=scroll(stem.textPanes().get(1));
            require(proseScroll.getHorizontalScrollBar().getMaximum()<=proseScroll.getHorizontalScrollBar().getVisibleAmount(),"code widened ordinary prose");
            if(width==320)require(codeScroll.getHorizontalScrollBar().getMaximum()>codeScroll.getHorizontalScrollBar().getVisibleAmount(),"narrow code has no horizontal scroll");
        }
        require(hasView(math,"MathView"),"formulas did not install native vector views");
        require(!hasView(code,"MathView"),"code installed a math view");
        require(codeFontIsPlain(stem.textPanes().getFirst().getUI().getRootView(stem.textPanes().getFirst())),"question emphasis made code bold");
        codePane.select(literal.indexOf("if ("),literal.indexOf("if (")+"if (a < b && b > 0) {".length());
        require(codePane.getSelectedText().equals("if (a < b && b > 0) {"),"code cannot be copied accurately");
        QuizRichText safe=new QuizRichText("```html\n<script>bad()</script>\n<img src='https://example.invalid/x'>\n```",16);
        require(text(safe.textPanes().getFirst()).contains("<script>bad()</script>"),"HTML code was treated as markup");
        require(!hasView(safe,"ImageView"),"code requested a remote image");
        questionSections(fenced);
    }
    private static void questionSections(String fenced)throws Exception {
        String rich=fenced+"\n\n식 $\\frac{a}{b}$도 비교해요.";
        QuizQuestion question=new QuizQuestion("rich","doc",QuizQuestion.Type.MCQ,"개념",STEM,
            List.of(new QuizQuestion.Option("A",rich,rich),new QuizQuestion.Option("B","`*a`",rich),
                new QuizQuestion.Option("C","`*p`",rich),new QuizQuestion.Option("D","값이 달라요.",rich)),
            "A",rich,List.of(),List.of(new QuizQuestion.Evidence("s",1,"근거")),false);
        QuizQuestionCard card=new QuizQuestionCard(question,1,ignored->{},true);
        card.restore(new QuizWorkbook.Answer("A",true));
        layoutAt(card,640);
        List<QuizRichText> richBodies=new ArrayList<>();collect(card,richBodies);
        require(richBodies.size()>=8,"some question/choice/answer/explanation sections bypass rich text");
        require(richBodies.stream().filter(body->hasNamed(body,"quiz-code-block")).count()>=7,"code boxes missing from choices or explanations");
        require(richBodies.stream().filter(body->hasView(body,"MathView")).count()>=7,"math missing from choices or explanations");
        long exactCodeBlocks=richBodies.stream().flatMap(body->body.textPanes().stream()).filter(pane->{
            try{return text(pane).contains("    printf")&&text(pane).contains("if (a < b && b > 0) {\n");}
            catch(Exception error){throw new RuntimeException(error);}
        }).count();
        require(exactCodeBlocks>=7,"correct-answer prefix damaged a fenced code block or its indentation");
    }
    private static boolean hasNamed(Container parent,String name){for(Component child:parent.getComponents())if(name.equals(child.getName())||child instanceof Container nested&&hasNamed(nested,name))return true;return false;}
    private static void collect(Container parent,List<QuizRichText> values){for(Component child:parent.getComponents())if(child instanceof QuizRichText rich)values.add(rich);else if(child instanceof Container nested)collect(nested,values);}
    private static String text(StudyHtmlPane pane)throws Exception{return pane.getDocument().getText(0,pane.getDocument().getLength());}
    private static JScrollPane scroll(StudyHtmlPane pane){return (JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,pane);}
    private static boolean hasView(QuizRichText rich,String name){return rich.textPanes().stream().anyMatch(pane->hasView(pane.getUI().getRootView(pane),name));}
    private static boolean hasView(View view,String name){if(view.getClass().getSimpleName().equals(name))return true;for(int i=0;i<view.getViewCount();i++)if(hasView(view.getView(i),name))return true;return false;}
    private static boolean codeFontIsPlain(View view){if(view instanceof GlyphView glyph&&glyph.getEndOffset()-glyph.getStartOffset()>1&&glyph.getFont().isBold())return false;for(int i=0;i<view.getViewCount();i++)if(!codeFontIsPlain(view.getView(i)))return false;return true;}
    private static void layoutAt(JComponent component,int width){component.setSize(width,Math.max(1,component.getPreferredSize().height));layout(component);component.setSize(width,component.getPreferredSize().height);layout(component);}
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    private static void require(boolean condition,String message){checks++;if(!condition)throw new AssertionError(message);}
}
