package dev.synesis.poc.pdf;

import java.awt.Component;
import java.awt.Container;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import javax.swing.JLabel;
import javax.swing.SwingUtilities;
import javax.swing.text.JTextComponent;

/** Headless answer-state contracts only; no app window, network or saved user data. */
public final class QuizConceptRevealTest {
    private static final String CONCEPT="정답명이 될 수 있는 학습 개념";

    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(()->{
            for(QuizQuestion.Type type:QuizQuestion.Type.values())revealAndRestore(type);
            blankConceptHasNoLabel();
        });
        System.out.println("QuizConceptRevealTest passed: concept titles stay hidden before answers, appear beside evidence after reveal, restore with saved state, hide on objective changes, and remain in tutor snapshots. No app windows or paid calls.");
    }

    private static void revealAndRestore(QuizQuestion.Type type) {
        QuizQuestion question=question(type,CONCEPT);
        List<QuizTutorRequest> tutor=new ArrayList<>();
        QuizQuestionCard card=new QuizQuestionCard(question,tutor::add);
        require(!visibleText(card).contains(CONCEPT),type+": concept leaked before reveal");
        require(!allText(card).contains(CONCEPT),type+": concept was created outside the answer reveal");
        card.tutorButton.doClick();
        equal(tutor.getFirst().question().concept(),CONCEPT,"tutor lost concept before reveal");
        if(question.selfComparison())card.answerInput.setText("내가 작성한 답변");
        else card.choiceButtons.get(type==QuizQuestion.Type.OX?"O":"A").doClick();
        card.checkButton.doClick();
        require(card.answerRevealed()&&card.answerPanel.isVisible(),type+": answer did not reveal");
        require(visibleText(card.answerPanel).contains("관련 개념: "+CONCEPT),type+": concept missing beside evidence");
        require(visibleText(card.answerPanel).contains("출제 근거:"),type+": source context missing");
        for(Component child:card.getComponents())if(child!=card.answerPanel)
            require(!visibleText(child).contains(CONCEPT),type+": concept escaped the answer panel");
        QuizWorkbook.Answer saved=card.snapshot();
        QuizQuestionCard restored=new QuizQuestionCard(question,tutor::add);
        restored.restore(saved);
        require(restored.answerRevealed()&&visibleText(restored).contains(CONCEPT),type+": revealed state did not restore concept");
        equal(restored.userAnswer(),saved.answer(),type+": restored user answer changed");
        restored.restore(new QuizWorkbook.Answer(saved.answer(),false));
        require(!restored.answerRevealed()&&!visibleText(restored).contains(CONCEPT),type+": unrevealed restore leaked concept");
        restored.restore(saved);
        restored.tutorButton.doClick();
        equal(tutor.getLast().question(),question,type+": tutor snapshot altered question");
        equal(tutor.getLast().question().concept(),CONCEPT,type+": tutor lost revealed concept");
        if(!question.selfComparison()) {
            restored.choiceButtons.get(type==QuizQuestion.Type.OX?"X":"B").doClick();
            require(!restored.answerRevealed()&&!visibleText(restored).contains(CONCEPT),type+": changed selection leaked concept");
        }
        restored.restore(null);
        require(!restored.answerRevealed()&&!visibleText(restored).contains(CONCEPT),type+": clearing progress leaked concept");
    }

    private static void blankConceptHasNoLabel() {
        QuizQuestionCard card=new QuizQuestionCard(question(QuizQuestion.Type.SHORT_ANSWER,""),ignored->{});
        card.checkButton.doClick();
        require(card.answerRevealed()&&!visibleText(card).contains("관련 개념:"),"blank concept created an empty heading");
    }

    private static QuizQuestion question(QuizQuestion.Type type,String concept) {
        List<QuizQuestion.Option> options=type==QuizQuestion.Type.MCQ
            ?List.of(new QuizQuestion.Option("A","첫 번째 선지","첫 판단의 이유"),
                new QuizQuestion.Option("B","두 번째 선지","둘째 판단의 이유"),
                new QuizQuestion.Option("C","세 번째 선지","셋째 판단의 이유"),
                new QuizQuestion.Option("D","네 번째 선지","넷째 판단의 이유")):List.of();
        String answer=switch(type){case OX->"O";case MCQ->"A";default->"모범 답변";};
        return new QuizQuestion("concept-reveal-"+type,"local-test-document",type,concept,
            "제시된 조건에 따라 답하시오.",options,answer,"자료의 판단 조건에 따른 설명이다.",
            type==QuizQuestion.Type.ESSAY?List.of("판단 조건"):List.of(),
            List.of(new QuizQuestion.Evidence("study:c1:e1",2,"판단 조건의 근거","saved_concept",List.of(),false)),false);
    }

    private static String visibleText(Component component) {
        if(!component.isVisible())return "";
        StringBuilder result=new StringBuilder(componentText(component));
        if(component instanceof Container container)
            for(Component child:container.getComponents())result.append('\n').append(visibleText(child));
        return result.toString();
    }
    private static String allText(Component component) {
        StringBuilder result=new StringBuilder(componentText(component));
        if(component instanceof Container container)
            for(Component child:container.getComponents())result.append('\n').append(allText(child));
        return result.toString();
    }
    private static String componentText(Component component) {
        if(component instanceof JLabel label)return label.getText();
        if(component instanceof JTextComponent text)try{return text.getDocument().getText(0,text.getDocument().getLength());}
            catch(javax.swing.text.BadLocationException error){throw new AssertionError(error);}
        return "";
    }
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private static void equal(Object actual,Object expected,String message){if(!Objects.equals(actual,expected))throw new AssertionError(message+": "+actual+" != "+expected);}
}
