package dev.synesis.poc.pdf;

import java.awt.*;
import java.util.List;
import javax.swing.*;
import javax.swing.text.GlyphView;
import javax.swing.text.View;

/** Saved/new statement clarity and option identity, without paid generation or app windows. */
public final class QuizQuestionPresentationTest {
    private static int checks;
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("QuizQuestionPresentationTest passed: "+checks+" section, OX guide, regular font and stable-option checks.");
        System.exit(0);
    }
    private static void run()throws Exception{
        String passage="성장 조건에는 국제 체제와 군사적 긴장이 포함된다.";
        String statement="제시문에 따르면 발전 조건을 지도자 개인의 능력만으로 설명할 수 있다.";
        String structured="### 제시문\n"+passage+"\n\n### 판단할 진술\n"+statement;
        var sections=QuizStemPresentation.sections(structured);
        check(sections.passage().equals(passage)&&sections.question().equals(statement),"sections were merged or guessed");
        String fenced="```md\n### 제시문\n예제\n### 문제\n코드이다.\n```";
        check(QuizStemPresentation.sections(fenced).question().equals(fenced),"code headings were interpreted as structure");
        String legacy=passage+"\n\n"+statement;
        check(QuizStemPresentation.sections(legacy).question().equals(legacy),"legacy statement was semantically rewritten");
        for(String text:List.of(structured,legacy)){
            QuizQuestion q=new QuizQuestion("ox","doc",QuizQuestion.Type.OX,"",text,List.of(),"X","해설",List.of(),List.of(),false);
            QuizQuestionCard card=new QuizQuestionCard(q,1,ignored->{},true);
            JTextArea guide=(JTextArea)named(card,"quiz-ox-guide");
            check(guide!=null&&guide.getText().equals(text.equals(structured)?QuizStemPresentation.OX_PASSAGE_GUIDE:QuizStemPresentation.OX_GUIDE),"OX choice instruction missing");
            check(guide.getFont().getSize()==18,"OX instruction should be slightly larger than the 16pt body");
            Component passagePanel=named(card,"quiz-question-passage");
            if(passagePanel!=null)check(guide.getParent()==passagePanel.getParent()
                &&guide.getParent().getComponentZOrder(guide)<passagePanel.getParent().getComponentZOrder(passagePanel),"OX instruction must precede passage");
            QuizRichText stem=(QuizRichText)named(card,"quiz-question-stem");
            layout(card,650);
            for(StudyHtmlPane pane:stem.textPanes())check(!bold(pane.getUI().getRootView(pane)),"question prose inherited bold");
            check((named(card,"quiz-question-passage")!=null)==text.equals(structured),"passage panel mismatch");
        }
        List<QuizQuestion.Option> options=List.of(new QuizQuestion.Option("B","자유시장주의 국가","B 해설"),
            new QuizQuestion.Option("D","식민지 국가","D 해설"),new QuizQuestion.Option("C","복지국가","C 해설"),
            new QuizQuestion.Option("A","발전국가","A 해설"));
        String prompt="국가가 산업·투자·자원 배분에 개입하는 국가 유형은 무엇인가?\n\n";
        String duplicate=prompt+"① 발전국가\n② 자유시장주의 국가\n③ 복지국가\n④ 식민지 국가";
        QuizQuestion q=new QuizQuestion("mcq","doc",QuizQuestion.Type.MCQ,"",duplicate,options,"A","해설",List.of(),List.of(),false);
        check(q.stem().equals(prompt+"① 자유시장주의 국가\n② 식민지 국가\n③ 복지국가\n④ 발전국가"),"embedded options differ from selectable order");
        check(q.answer().equals("A")&&q.options().equals(options),"alignment changed option identity or correct answer");
        check(QuizStemPresentation.alignOptions(q.stem(),options).equals(q.stem()),"alignment is not idempotent");
        QuizQuestionCard card=new QuizQuestionCard(q,1,ignored->{},true);
        card.restore(new QuizWorkbook.Answer("A",true));
        check(card.userAnswer().equals("A")&&card.answerRevealed(),"saved answer lost its selected option");
        for(String unrelated:List.of("```text\n"+duplicate+"\n```",duplicate+"\n별도의 다음 질문이다.",
                prompt+"① 조건 1\n② 조건 2\n③ 조건 3\n④ 조건 4"))
            check(QuizStemPresentation.alignOptions(unrelated,options).equals(unrelated),"unrelated numbered material was rewritten");
    }
    private static boolean bold(View view){
        if(view instanceof GlyphView glyph&&glyph.getFont().isBold())return true;
        for(int i=0;i<view.getViewCount();i++)if(bold(view.getView(i)))return true;
        return false;
    }
    private static Component named(Container parent,String name){
        for(Component c:parent.getComponents()){
            if(name.equals(c.getName()))return c;
            if(c instanceof Container nested){Component found=named(nested,name);if(found!=null)return found;}
        }
        return null;
    }
    private static void layout(Container parent,int width){
        parent.setSize(width,1);parent.setSize(width,parent.getPreferredSize().height);layoutTree(parent);
    }
    private static void layoutTree(Container parent){parent.doLayout();for(Component c:parent.getComponents())if(c instanceof Container nested&&c.isVisible())layoutTree(nested);}
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
}
