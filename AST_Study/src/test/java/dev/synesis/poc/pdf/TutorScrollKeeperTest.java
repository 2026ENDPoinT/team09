package dev.synesis.poc.pdf;

import java.awt.*;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.*;

/** Real viewport/layout ordering without a window, model calls or user data. */
public final class TutorScrollKeeperTest {
    private static JPanel messages;
    private static JScrollPane scroll;
    private static TutorScrollKeeper keeper;

    public static void main(String[] args)throws Exception {
        run(TutorScrollKeeperTest::readingAnchorSurvivesRebuild);
        run(TutorScrollKeeperTest::bottomFollowsMeasuredHeight);
        run(TutorScrollKeeperTest::userInputCancelsPendingRestore);
        run(TutorScrollKeeperTest::fineUpwardInputDetachesBeforePixelMovement);
        run(TutorScrollKeeperTest::nearBottomManualPositionDoesNotSnap);
        run(TutorScrollKeeperTest::downwardInputResumesOnlyAtEnd);
        run(TutorScrollKeeperTest::explicitEndResumesFollowing);
        fractionalInputSurvivesStreamingTicks();
        run(TutorScrollKeeperTest::closeCancelsPendingRestore);
        run(TutorScrollKeeperTest::replacedHtmlCannotRevealOldCaret);
        System.out.println("TutorScrollKeeperTest OK: reading anchor, completion layout, coalescing, manual input, close, HTML caret");
    }

    private static void run(Throwing task)throws Exception {
        AtomicReference<Throwable> failure=new AtomicReference<>();
        SwingUtilities.invokeAndWait(()->{
            try {fixture();task.run();}catch(Throwable error){failure.set(error);}
        });
        drain();
        if(failure.get()!=null)throw new AssertionError(failure.get());
    }

    private static void fixture() {
        messages=new JPanel();messages.setLayout(new BoxLayout(messages,BoxLayout.Y_AXIS));
        for(int i=0;i<10;i++)row("answer-"+i,120);
        scroll=new JScrollPane(messages);scroll.getViewport().setExtentSize(new Dimension(360,200));
        keeper=new TutorScrollKeeper(scroll,messages);layout();
    }

    private static void row(String key,int height) {
        JPanel row=new JPanel();row.putClientProperty(TutorScrollKeeper.ANCHOR,key);
        row.setMinimumSize(new Dimension(0,height));row.setPreferredSize(new Dimension(360,height));
        row.setMaximumSize(new Dimension(Integer.MAX_VALUE,height));messages.add(row);
    }

    private static void layout() {
        scroll.getViewport().setViewSize(new Dimension(360,messages.getPreferredSize().height));messages.doLayout();
    }

    private static int y(){return scroll.getViewport().getViewPosition().y;}
    private static void at(int y){scroll.getViewport().setViewPosition(new Point(0,y));}

    private static void readingAnchorSurvivesRebuild() {
        at(370);var position=keeper.capture(false);
        messages.removeAll();
        for(int i=0;i<10;i++)row("answer-"+i,i==0?190:120);
        row("feedback",40);
        keeper.restore(position);
        // An animation callback runs while the rebuilt hierarchy still reports zero.
        at(0);keeper.restore(keeper.capture(false));
        later(()->check(y()==440,"reading anchor lost after completion/reflow: "+y()));
    }

    private static void bottomFollowsMeasuredHeight() {
        at(1000);var position=keeper.capture(false);
        row("new-answer",400);
        // Deliberately stale scrollbar bounds: the restore must use content height.
        scroll.getVerticalScrollBar().setValues(0,200,0,200);
        keeper.restore(position);
        later(()->check(y()==1400,"bottom used stale maximum: "+y()));
    }

    private static void userInputCancelsPendingRestore() {
        at(1000);keeper.restore(keeper.capture(false));
        keeper.userInput();at(240);
        later(()->check(y()==240,"queued auto-scroll overrode manual scrolling: "+y()));
    }

    private static void closeCancelsPendingRestore() {
        at(1000);keeper.restore(keeper.capture(false));keeper.close();at(120);
        later(()->check(y()==120,"closed chat applied a stale restore"));
    }

    private static void fineUpwardInputDetachesBeforePixelMovement() {
        at(1000);keeper.restore(keeper.capture(false));
        keeper.wheelInput(-.001);
        var position=keeper.capture(false);
        check(!position.followEnd(),"subpixel upward input reattached before movement");
        row("stream",50);keeper.restore(position);
        later(()->check(y()==1000,"stream growth overrode subpixel intent: "+y()));
    }

    private static void nearBottomManualPositionDoesNotSnap() {
        at(1000);keeper.wheelInput(-.02);at(999);
        var position=keeper.capture(false);
        check(!position.followEnd(),"one-pixel scroll stayed inside automatic follow threshold");
        keeper.restore(position);
        later(()->check(y()==999,"near-bottom reading position snapped back: "+y()));
    }

    private static void downwardInputResumesOnlyAtEnd() {
        keeper.wheelInput(.02);at(999);
        check(!keeper.capture(false).followEnd(),"downward scroll reattached before reaching bottom");
        at(1000);check(keeper.capture(false).followEnd(),"manual return to bottom did not resume following");
        var position=keeper.capture(false);row("stream",50);keeper.restore(position);
        later(()->check(y()==1050,"resumed follow did not track growing reply: "+y()));
    }

    private static void explicitEndResumesFollowing() {
        at(999);keeper.wheelInput(-.01);
        check(keeper.capture(true).followEnd(),"new question could not force bottom");
        at(1000);check(keeper.capture(false).followEnd(),"explicit end left manual detachment active");
    }

    private static void fractionalInputSurvivesStreamingTicks()throws Exception {
        SwingUtilities.invokeAndWait(()->{fixture();at(1000);});
        var wheel=new dev.synesis.poc.ui.PreciseWheelInput();
        for(int tick=0;tick<80;tick++) {
            SwingUtilities.invokeAndWait(()->{
                keeper.wheelInput(-.002);
                var event=new java.awt.event.MouseWheelEvent(scroll,java.awt.event.MouseEvent.MOUSE_WHEEL,
                    System.currentTimeMillis(),0,10,10,10,10,0,false,
                    java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,3,0,-.002);
                wheel.scroll(scroll,event);
                keeper.restore(keeper.capture(false)); // thinking/streaming repaint between tiny deltas
            });
            drain();
        }
        SwingUtilities.invokeAndWait(()->check(y()<1000 && y()>980,"fine trackpad travel was lost or snapped: "+y()));
    }

    private static void replacedHtmlCannotRevealOldCaret() {
        StudyHtmlPane text=new StudyHtmlPane(true);text.setEditable(false);text.setText("<p>old</p>");
        JPanel first=(JPanel)messages.getComponent(0);first.add(text);
        layout();first.doLayout();text.setSize(300,100);
        at(550);
        text.setCaretPosition(text.getDocument().getLength());
        text.setText("<p>replacement</p>");
        later(()->check(y()==550,"HTML replacement scrolled an earlier message into view: "+y()));
    }

    private static Throwable deferredFailure;
    private static void later(Runnable check) {
        SwingUtilities.invokeLater(()->{try{check.run();}catch(Throwable error){deferredFailure=error;}});
    }
    private static void drain()throws Exception {
        SwingUtilities.invokeAndWait(()->{});SwingUtilities.invokeAndWait(()->{});
        if(deferredFailure!=null){Throwable failure=deferredFailure;deferredFailure=null;throw new AssertionError(failure);}
    }
    private static void check(boolean pass,String message){if(!pass)throw new AssertionError(message);}
    private interface Throwing{void run()throws Exception;}
}
