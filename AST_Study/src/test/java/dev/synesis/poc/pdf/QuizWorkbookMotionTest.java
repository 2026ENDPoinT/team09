package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibrarySectionMotion;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.util.List;
import javax.swing.*;

/** Real sidebar motion on a displayable, window-free quiz hierarchy; deterministic frame times. */
public final class QuizWorkbookMotionTest {
    private static int checks;
    public static void main(String[] args)throws Exception{
        try{SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});}
        catch(Throwable failure){failure.printStackTrace();System.exit(1);return;}
        System.out.println("QuizWorkbookMotionTest passed: "+checks+" checks; enter/exit sidebar effect, bounded snapshots and release, answer persistence, latest navigation, PDF reset, hidden cleanup and reduced motion. No app windows or API calls.");System.exit(0);
    }
    private static QuizWorkbook book(String id){
        QuizQuestion question=new QuizQuestion(id+"-q","motion-doc",QuizQuestion.Type.OX,"개념","옳은 문장인지 판단해 보세요.",List.of(),"O","문제의 조건에 따라 판단해요.",List.of(),List.of(),false);
        return new QuizWorkbook(id,"motion-doc",id+" 문제집",QuizPanel.Theme.CONCEPT,"중",1,1,1,.01,"",List.of(question));
    }
    private static void run()throws Exception{
        JPanel host=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};
        QuizPanel panel=new QuizPanel();panel.reset(12,"motion-doc");panel.setReady(true);panel.addWorkbook(book("first"));panel.addWorkbook(book("second"));
        host.add(panel);host.setSize(1000,850);host.addNotify();layout(host);
        LibrarySectionMotion motion=(LibrarySectionMotion)get(panel,"workbookMotion");
        try{
            panel.workbookButtons.get("first").doClick(0);
            check(motion.active()&&panel.currentWorkbookId().isEmpty(),"enter must animate the outgoing list before switching");
            enter(motion);check(panel.currentWorkbookId().equals("first")&&motion.active(),"workbook destination must enter with the sidebar effect");
            BufferedImage image=(BufferedImage)get(motion,"picture");check((long)image.getWidth()*image.getHeight()<=400_000,"unbounded transition image");
            finish(motion);check(!motion.active()&&get(motion,"picture")==null,"enter retains preview pixels");
            QuizQuestionCard card=panel.cards.getFirst();card.choiceButtons.get("O").doClick(0);card.checkButton.doClick(0);card.bookmarkButton.doClick(0);
            panel.setGenerating(true,"문항 출제 중");
            panel.workbookBack.doClick(0);check(motion.active()&&panel.currentWorkbookId().equals("first"),"back must animate the outgoing workbook");
            enter(motion);check(panel.currentWorkbookId().isEmpty()&&panel.cards.isEmpty()&&motion.active(),"list must enter with the same effect");
            check((boolean)get(panel,"generating"),"navigation cancelled generation");finish(motion);panel.setGenerating(false,"");
            panel.workbookButtons.get("first").doClick(0);enter(motion);finish(motion);
            check(panel.cards.getFirst().snapshot().revealed()&&panel.cards.getFirst().snapshot().bookmarked(),"round trip lost saved answers or checks");
            panel.workbookBack.doClick(0);enter(motion);finish(motion);
            panel.workbookButtons.get("first").doClick(0);panel.workbookButtons.get("second").doClick(0);enter(motion);finish(motion);
            check(panel.currentWorkbookId().equals("second"),"rapid clicks opened a stale workbook");
            panel.workbookBack.doClick(0);panel.reset(12,"new-doc");
            check(!motion.active()&&get(motion,"pending")==null&&panel.currentWorkbookId().isEmpty(),"PDF reset retained a queued transition");
            panel.reset(12,"motion-doc");panel.addWorkbook(book("first"));
            Object previous=UIManager.get("synesis.reduceMotion");UIManager.put("synesis.reduceMotion",true);
            try{panel.workbookButtons.get("first").doClick(0);check(panel.currentWorkbookId().equals("first")&&!motion.active(),"reduced motion must switch immediately");}
            finally{UIManager.put("synesis.reduceMotion",previous);}
            panel.workbookBack.doClick(0);check(motion.active(),"exit did not begin");
            host.removeNotify();check(!motion.active()&&get(motion,"picture")==null&&get(motion,"pending")==null,"hidden quiz retained motion work");
        }finally{motion.cancel();if(host.isDisplayable())host.removeNotify();}
    }
    private static void enter(LibrarySectionMotion motion)throws Exception{motion.advance((long)get(motion,"started")+180_000_000L);}
    private static void finish(LibrarySectionMotion motion)throws Exception{motion.advance((long)get(motion,"started")+600_000_000L);}
    private static Object get(Object value,String name)throws Exception{Field f=value.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(value);}
    private static void layout(Container parent){parent.doLayout();for(Component c:parent.getComponents())if(c.isVisible()&&c instanceof Container nested)layout(nested);}
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
}
