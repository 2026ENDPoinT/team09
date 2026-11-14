package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Offline viewport-overlay regression. No application windows or provider calls. */
public final class QuizNavigationDockTest {
    private static int checks;
    public static void main(String[] args)throws Exception{
        try{SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});}
        catch(Throwable failure){failure.printStackTrace();System.exit(1);return;}
        System.out.println("QuizNavigationDockTest passed: "+checks+" checks; fixed bottom position, narrow/wide alignment, scroll handoff, unobscured final answer, list/reset visibility and navigation. No windows or API calls.");
        System.exit(0);
    }
    private static void run()throws Exception{
        QuizPanel panel=new QuizPanel();panel.reset(12,"dock-test");panel.setReady(true);
        QuizQuestion question=new QuizQuestion("q1","dock-test",QuizQuestion.Type.OX,"개념",
            "다음 문장이 옳은지 판단해 보세요. ".repeat(12),List.of(),"O",
            "해설을 천천히 읽어 보세요. ".repeat(80),List.of(),List.of(),false);
        QuizQuestion second=new QuizQuestion("q2","dock-test",QuizQuestion.Type.OX,"개념","두 번째 문제예요.",List.of(),"X","설명이에요.",List.of(),List.of(),false);
        panel.showQuestions(List.of(question,second));
        var field=QuizPanel.class.getDeclaredField("scroll");field.setAccessible(true);JScrollPane scroll=(JScrollPane)field.get(panel);
        JPanel surface=(JPanel)named(panel,"quiz-fixed-navigation");check(surface!=null&&surface.isVisible(),"dock missing from solving screen");
        check(!SwingUtilities.isDescendingFrom(surface,scroll.getViewport()),"dock must not scroll with the document");
        for(int width:new int[]{520,1060,360}){
            panel.setSize(width,720);for(int i=0;i<4;i++)layout(panel);
            Point initial=SwingUtilities.convertPoint(surface,0,0,panel);
            Point viewOrigin=SwingUtilities.convertPoint(scroll.getViewport(),0,0,panel);
            check(viewOrigin.y+scroll.getViewport().getHeight()<=initial.y,"fixed navigation overlaps the scrolling pixel region");
            check(surface.getParent() instanceof JComponent parent&&parent.isOptimizedDrawingEnabled(),"dock disables optimized sibling painting");
            check(initial.y+surface.getHeight()<=panel.getHeight()&&initial.y>panel.getHeight()-110,"dock not at bottom");
            Insets insets=((JComponent)scroll.getViewport().getView()).getInsets();
            int expectedWidth=panel.studyView.navigationColumn(scroll.getViewport().getWidth()-insets.left-insets.right).width;
            check(surface.getWidth()==expectedWidth,"dock not aligned with workbook column including the index");
            scroll.getViewport().setViewPosition(new Point(0,240));
            check(initial.equals(SwingUtilities.convertPoint(surface,0,0,panel)),"scroll moved the dock");
            check(surface.contains(20,30)&&surface.contains(20,3),"reserved footer must forward wheel input across its shadow band too");
            panel.cards.getFirst().choiceButtons.get("O").doClick(0);panel.cards.getFirst().checkButton.doClick(0);
            for(int i=0;i<3;i++)layout(panel);
            scroll.getViewport().setViewPosition(new Point(0,Math.max(0,scroll.getViewport().getViewSize().height-scroll.getViewport().getHeight())));
            QuizQuestionCard card=panel.cards.getFirst();Point bottom=SwingUtilities.convertPoint(card,0,card.getHeight(),panel);
            check(bottom.y<=initial.y,"final answer hidden behind dock: width="+width+", cardBottom="+bottom.y+", dockTop="+initial.y+", view="+scroll.getViewport().getViewSize()+", preferred="+scroll.getViewport().getView().getPreferredSize()+", offset="+scroll.getViewport().getViewPosition());
            scroll.getViewport().setViewPosition(new Point(0,0));
            MouseWheelEvent wheel=new MouseWheelEvent(surface,MouseEvent.MOUSE_WHEEL,0,0,20,35,20,35,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,0,.5);
            surface.dispatchEvent(wheel);check(wheel.isConsumed()&&scroll.getViewport().getViewPosition().y>0,"wheel over dock must reach document");
            paint(panel,Path.of("build/quiz-navigation-dock-20261023/dock-"+width+".png"));
        }
        panel.studyView.next.doClick(0);check(panel.studyView.currentIndex()==1,"next button lost its handler");
        panel.studyView.previous.doClick(0);check(panel.studyView.currentIndex()==0&&panel.cards.getFirst().answerRevealed(),"previous lost saved answer");
        panel.showWorkbookList();check(!surface.isVisible(),"dock remains on workbook list");
        panel.showQuestions(List.of(question,second));check(surface.isVisible(),"dock does not return on reopen");
        panel.reset(0,"");check(!surface.isVisible(),"dock remains after PDF reset");
    }
    private static void paint(JComponent panel,Path path)throws Exception{
        Files.createDirectories(path.getParent());BufferedImage image=new BufferedImage(panel.getWidth(),panel.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();try{panel.printAll(g);}finally{g.dispose();}ImageIO.write(image,"png",path.toFile());
    }
    private static Component named(Container parent,String name){for(Component c:parent.getComponents()){if(name.equals(c.getName()))return c;if(c instanceof Container nested){Component found=named(nested,name);if(found!=null)return found;}}return null;}
    private static void layout(Container parent){invalidateTree(parent);layoutTree(parent);}
    private static void invalidateTree(Container parent){for(Component c:parent.getComponents())if(c instanceof Container nested)invalidateTree(nested);parent.invalidate();}
    private static void layoutTree(Container parent){parent.doLayout();for(Component c:parent.getComponents())if(c.isVisible()&&c instanceof Container nested)layoutTree(nested);}
    private static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
}
