package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.util.List;

/** Correct option numbers must stay prose; math answers and explanations own separate bounds. */
public final class QuizAnswerLayoutTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});
        System.out.println("PASS: math answer/explanation spacing, wrapping and repeated width changes");
        System.exit(0);
    }
    private static void run()throws Exception {
        String formula="리만합은 $\\sum_{i=1}^{n} f(x_i)\\Delta x$ 이고, 분할을 무한히 세분할 때 그 극한은 $\\int_a^b f(x)\\,dx$ 이다.";
        QuizQuestion question=new QuizQuestion("math-answer","doc",QuizQuestion.Type.MCQ,"적분","옳은 선지를 고르세요.",
            List.of(new QuizQuestion.Option("A",formula,"분할의 극한이에요."),new QuizQuestion.Option("B","두 번째 선지","해설"),
                new QuizQuestion.Option("C","세 번째 선지","해설"),new QuizQuestion.Option("D","네 번째 선지","해설")),
            "A",formula+"\n\n"+formula,List.of(),List.of(new QuizQuestion.Evidence("s",1,"근거")),false);
        for(boolean focused:new boolean[]{false,true}) {
        QuizQuestionCard card=new QuizQuestionCard(question,1,request->{},focused);
        card.restore(new QuizWorkbook.Answer("A",true));
        for(int width:new int[]{640,320,900,400,640}) {
            card.setSize(width,card.getPreferredSize().height);layout(card);
            card.setSize(width,card.getPreferredSize().height);layout(card);
            java.util.List<JPanel> sections=java.util.Arrays.stream(card.answerPanel.getComponents()).filter(c->c instanceof JPanel section&&section.getComponentCount()>1&&section.getComponent(0) instanceof JLabel).map(c->(JPanel)c).toList();
            JPanel answer=sections.get(0),explanation=sections.get(1);
            require(answer.getY()+answer.getHeight()+14<=explanation.getY(),"answer overlaps explanation");
            require(answer.getY()+answer.getHeight()<=card.answerPanel.getHeight(),"answer exceeds its parent");
            for(JPanel section:List.of(answer,explanation)) {
                Component title=section.getComponent(0);
                QuizRichText body=(QuizRichText)section.getComponent(1);
                require(title.getY()+title.getHeight()+10<=body.getY(),"heading overlaps math text");
                require(body.getY()+body.getHeight()<=section.getHeight(),"math exceeds section bounds");
                for(StudyHtmlPane pane:body.textPanes())for(int offset=1;offset<pane.getDocument().getLength();offset++) {
                    var bounds=pane.modelToView2D(offset);
                    require(bounds==null||bounds.getMaxY()<=pane.getHeight()+1,"math text exceeds its allocated height");
                }
            }
            QuizRichText correct=(QuizRichText)answer.getComponent(1);
            StudyHtmlPane correctPane=correct.textPanes().getFirst();
            require(!correctPane.getText().contains("<ol"),"correct option became an ordered Markdown list");
            require(correctPane.getDocument().getText(0,correctPane.getDocument().getLength()).contains("①"),"option number lost");
        }
        }
    }
    private static void layout(Container parent) {
        parent.doLayout();
        for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);
    }
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
