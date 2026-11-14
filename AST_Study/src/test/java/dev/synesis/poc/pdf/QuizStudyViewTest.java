package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.List;
import java.util.*;
import java.util.concurrent.atomic.AtomicReference;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Offline regression: 120-question navigation, filtered review, skipped answers and incremental arrival. */
public final class QuizStudyViewTest {
    private static final String DOC="study-view-fixture";
    private static int checks;
    public static void main(String[] args)throws Exception{
        Path output=Path.of("build/quiz-study-view");Files.createDirectories(output);
        try {SwingUtilities.invokeAndWait(()->{try{run(output);}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable failure){failure.printStackTrace();System.exit(1);return;}
        System.out.println("QuizStudyViewTest passed: "+checks+" checks, one live card for 120 questions, persisted bookmarks/skips, filtered navigation, live arrivals, narrow/wide layout. No API or app windows.");System.exit(0);
    }
    private static QuizPanel panel(){QuizPanel p=new QuizPanel();p.reset(12,DOC);p.setReady(true);return p;}
    private static QuizQuestion q(int i){return new QuizQuestion("q"+i,DOC,QuizQuestion.Type.OX,"개념 "+i,
        "함수의 극한은 \\(\\lim_{x \\to a}f(x)=L\\)과 같이 표현할 수 있어요.",List.of(),"O",
        "정의에 따라 입력값이 주어진 점에 가까워질 때 함숫값이 일정한 값에 가까워지는지를 확인해요.",List.of(),List.of(),false);}
    private static QuizWorkbook book(List<QuizQuestion> questions){return new QuizWorkbook("book",DOC,"극한과 연속",QuizPanel.Theme.CONCEPT,"중",120,1,1,.01,"",questions);}
    private static void run(Path output)throws Exception{
        List<QuizQuestion> all=new ArrayList<>();for(int i=0;i<120;i++)all.add(q(i));
        QuizPanel p=panel();AtomicReference<Map<String,QuizWorkbook.Answer>> saved=new AtomicReference<>(Map.of());
        p.setWorkbookProgressHandler((b,a)->saved.set(a));p.addWorkbook(book(all));p.workbookButtons.get("book").doClick(0);
        p.studyView.heading("극한과 연속","개념 완성 N제 · 난이도 중 · 120문제\n생성 2026.10.23","점검 안내");
        var title=(javax.swing.text.JTextComponent)named(p.studyView,"quiz-workbook-title");
        var meta=(javax.swing.text.JTextComponent)named(p.studyView,"quiz-workbook-metadata");
        var created=(javax.swing.text.JTextComponent)named(p.studyView,"quiz-workbook-created");
        check(title.getText().equals("극한과 연속")&&meta.getText().contains("120문제")&&!meta.getText().contains("생성"),"title and metadata hierarchy lost");
        check(created.getText().contains("2026.10.23"),"creation date lost");
        paint(p,1060,1050,output.resolve("heading-wide.png"));
        check(meta.getY()<title.getY()&&Color.WHITE.equals(QuizPlayDesign.PAGE),"metadata must be above the title on a white page");
        QuizQuestionCard reading=p.cards.getFirst();
        Component ox=reading.choiceButtons.get("O").getParent(),xx=reading.choiceButtons.get("X").getParent();
        check(ox.getY()==xx.getY()&&ox.getX()<xx.getX(),"wide OX answers must be side by side");
        paint(p,360,1050,output.resolve("heading-compact.png"));
        check(ox.getY()<xx.getY()&&ox.getX()==xx.getX(),"compact OX answers must stack");
        check(reading.checkButton.isVisible()&&reading.unknownButton.isVisible()&&reading.tutorButton.getText().equals("튜터에게 이 문제 해설 요청하기"),"existing solving actions lost");
        check(QuizPlayDesign.QUESTION_PAPER.equals(Color.WHITE),"question paper must stay white");
        check(p.cards.size()==1&&p.studyView.questionCount()==120,"120 questions allocated multiple cards");
        QuizQuestionCard first=p.cards.getFirst();first.bookmarkButton.doClick(0);first.choiceButtons.get("O").doClick(0);first.checkButton.doClick(0);
        check(saved.get().get("q0").bookmarked()&&saved.get().get("q0").revealed(),"grade or bookmark not saved");
        p.studyView.next.doClick(0);check(p.studyView.currentIndex()==1,"next question");
        p.cards.getFirst().unknownButton.doClick(0);
        check(saved.get().get("q1").skipped()&&saved.get().get("q1").revealed(),"unknown without answer must be a saved skipped result");
        check(!p.cards.getFirst().choiceButtons.get("O").isEnabled(),"graded answer could be overwritten");
        p.studyView.select(119);p.cards.getFirst().bookmarkButton.doClick(0);p.studyView.marked.doClick(0);
        p.studyView.previous.doClick(0);check(p.studyView.currentIndex()==0,"filtered previous did not skip unmarked questions");
        p.studyView.next.doClick(0);check(p.studyView.currentIndex()==119,"filtered next did not skip unmarked questions");
        p.cards.getFirst().bookmarkButton.doClick(0);check(p.studyView.currentIndex()==0,"unmark current did not retain a marked question");
        p.cards.getFirst().bookmarkButton.doClick(0);check(p.cards.isEmpty()&&!p.studyView.next.isEnabled(),"empty checked filter should display empty state");
        p.studyView.all.doClick(0);check(p.cards.size()==1&&p.cards.getFirst().answerRevealed(),"leaving checked filter lost saved grade");
        Path folder=Files.createTempDirectory("quiz-study-progress-");
        try{
            QuizWorkbookStore.saveAnswers(folder,book(all),saved.get());
            var restored=QuizWorkbookStore.loadAnswers(folder,book(all));
            check(restored.get("q1").skipped()&&restored.get("q1").revealed(),"skip was dropped by progress validation");
            p.cards.getFirst().bookmarkButton.doClick(0);QuizWorkbookStore.saveAnswers(folder,book(all),saved.get());
            restored=QuizWorkbookStore.loadAnswers(folder,book(all));check(restored.get("q0").bookmarked(),"bookmark did not survive disk round trip");
            QuizPanel second=panel();second.addWorkbook(book(all));second.setWorkbookOpenHandler(b->second.openWorkbook(b,QuizWorkbookStore.loadAnswers(folder,b)));second.workbookButtons.get("book").doClick(0);
            check(second.cards.getFirst().snapshot().bookmarked()&&second.cards.getFirst().answerRevealed(),"reopening discarded saved state");second.reset(0,"");
        }finally{try(var paths=Files.walk(folder)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
        for(int i=0;i<120;i++){p.studyView.select(i);check(p.cards.size()==1,"navigation retained old card "+i);}
        p.studyView.select(0);paint(p,1060,1050,output.resolve("wide.png"));paint(p,520,1050,output.resolve("narrow.png"));paint(p,360,1050,output.resolve("compact.png"));
        check(p.cards.getFirst().getWidth()>200,"narrow card is clipped");
        p.reset(12,DOC);p.setGenerating(true,"생성 중");p.acceptGenerationSnapshot(book(all.subList(0,2)));p.workbookButtons.get("book").doClick(0);
        QuizQuestionCard active=p.cards.getFirst();active.choiceButtons.get("X").doClick(0);active.bookmarkButton.doClick(0);
        p.acceptGenerationSnapshot(book(all));check(p.cards.getFirst()==active,"arrival replaced live card");
        check(active.userAnswer().equals("X")&&active.snapshot().bookmarked()&&p.studyView.questionCount()==120,"arrival lost user work");
        p.addWorkbook(book(all));check(p.cards.getFirst()==active,"completion replaced live card");
        JButton menu=p.workbookMenus.get("book");check(menu!=null&&menu.getComponentPopupMenu().getComponentCount()==2,"workbook actions menu missing");
        p.renameWorkbook("book","복습 문제집");check(p.workbooks().getFirst().title().equals("복습 문제집")&&p.cards.getFirst()==active,"rename interrupted active solving");
        p.removeWorkbook("book");check(p.workbooks().isEmpty()&&p.cards.isEmpty()&&p.currentWorkbookId().isEmpty(),"delete left workbook or active view");
        p.setGenerating(true,"생성 중");p.acceptGenerationSnapshot(book(all));p.addWorkbook(book(all));check(p.workbooks().isEmpty(),"stale generation resurrected deleted workbook");p.reset(0,"");
    }
    private static void paint(QuizPanel p,int width,int height,Path file)throws Exception{
        p.setSize(width,height);for(int i=0;i<4;i++)layout(p);
        BufferedImage image=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();try{p.printAll(g);}finally{g.dispose();}ImageIO.write(image,"png",file.toFile());
    }
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested&&child.isVisible())layout(nested);}
    private static Component named(Container parent,String name){for(Component c:parent.getComponents()){if(name.equals(c.getName()))return c;if(c instanceof Container child){Component found=named(child,name);if(found!=null)return found;}}return null;}
    private static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
}
