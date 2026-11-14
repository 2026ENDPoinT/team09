package dev.synesis.poc.pdf;

import java.awt.Dimension;
import java.awt.Point;
import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import javax.swing.JComponent;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JViewport;
import javax.swing.KeyStroke;
import javax.swing.SwingUtilities;
import javax.swing.Timer;

/** Deterministic wheel input and simulated frame clocks; never creates a window. */
public final class QuizScrollMotionTest {
    private static int checks;
    private static final class Pane extends QuizScrollPane {
        boolean showing=true;
        Pane(){super(view(),JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);}
        @Override public boolean isShowing(){return showing;}
        void key(){processKeyBinding(KeyStroke.getKeyStroke(KeyEvent.VK_PAGE_DOWN,0),
            new KeyEvent(this,KeyEvent.KEY_PRESSED,0,0,KeyEvent.VK_PAGE_DOWN,KeyEvent.CHAR_UNDEFINED),
            JComponent.WHEN_ANCESTOR_OF_FOCUSED_COMPONENT,true);}
    }
    private static JPanel view(){JPanel view=new JPanel();view.setPreferredSize(new Dimension(1000,5000));return view;}
    private static Pane pane() {
        Pane pane=new Pane();pane.setSize(240,180);pane.doLayout();pane.getViewport().doLayout();
        pane.getVerticalScrollBar().setUnitIncrement(8);pane.getHorizontalScrollBar().setUnitIncrement(8);return pane;
    }
    private static MouseWheelEvent wheel(JScrollPane pane,double rotation,int modifiers,int type) {
        MouseWheelEvent event=new MouseWheelEvent(pane,MouseEvent.MOUSE_WHEEL,0,modifiers,40,40,40,40,0,false,
            type,3,(int)rotation,rotation);pane.dispatchEvent(event);return event;
    }
    private static MouseWheelEvent wheel(JScrollPane pane,double rotation){return wheel(pane,rotation,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);}
    private static void check(boolean value,String label){checks++;if(!value)throw new AssertionError(label);}
    private static void answerWheelHandoff() {
        QuizQuestion question=new QuizQuestion("wheel-answer","wheel-document",QuizQuestion.Type.ESSAY,
            "","답을 작성해 보세요.",java.util.List.of(),"모범답안","",java.util.List.of(),java.util.List.of(),false);
        QuizQuestionCard card=new QuizQuestionCard(question,ignored->{});
        JPanel body=view();body.setLayout(null);body.add(card);card.setBounds(0,0,600,600);card.doLayout();
        Pane outer=pane();outer.setViewportView(body);outer.doLayout();outer.getViewport().doLayout();
        JScrollPane input=(JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,card.answerInput);
        input.setSize(400,160);input.doLayout();input.getViewport().doLayout();
        check(wheel(input,.5).isConsumed()&&outer.getVerticalScrollBar().getValue()>0,
            "empty answer forwards precise wheel input to the quiz page");
        check(input.getVerticalScrollBar().getValue()==0,"empty answer stays stationary");
        card.answerInput.setText("짧은 답변");input.doLayout();input.getViewport().doLayout();
        outer.getVerticalScrollBar().setValue(100);
        wheel(input,-.5);
        check(outer.getVerticalScrollBar().getValue()<100,"short answer forwards upward wheel input too");
        card.answerInput.setText("긴 답변 줄\n".repeat(40));input.doLayout();input.getViewport().doLayout();
        input.getVerticalScrollBar().setValue(0);int pagePosition=outer.getVerticalScrollBar().getValue();
        wheel(input,.5);
        check(input.getVerticalScrollBar().getValue()>0&&outer.getVerticalScrollBar().getValue()==pagePosition,
            "overflowing answer scrolls internally without moving the quiz page");
        card.answerInput.setText("");input.doLayout();input.getViewport().doLayout();
        wheel(input,.5);
        check(outer.getVerticalScrollBar().getValue()>pagePosition,"deleting a long answer restores page scrolling");
        input.removeNotify();outer.removeNotify();
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            answerWheelHandoff();
            Pane pane=pane();
            check(pane.getViewport().getScrollMode()==JViewport.BLIT_SCROLL_MODE,"quiz retains opaque pixel reuse");
            check(wheel(pane,1).isConsumed()&&pane.getVerticalScrollBar().getValue()==18,
                "coarse wheel immediately matches PDF distance");
            pane.scrollToTop();
            for(int i=0;i<100;i++)wheel(pane,.01);
            check(pane.getVerticalScrollBar().getValue()==18,"fractional trackpad distance matches PDF");
            for(int i=0;i<100;i++)wheel(pane,-.01);
            check(pane.getVerticalScrollBar().getValue()==0,"fractional trackpad reverses without loss");
            pane.getVerticalScrollBar().setValue(300);wheel(pane,.5);
            check(pane.getVerticalScrollBar().getValue()==309,"direct navigation resets input accumulation");
            pane.scrollToTop();wheel(pane,1,0,MouseWheelEvent.WHEEL_BLOCK_SCROLL);
            check(pane.getVerticalScrollBar().getValue()==18,"block wheel uses the same shared pixel distance");
            pane.scrollToTop();check(!wheel(pane,-1).isConsumed(),"upper boundary does not trap input");
            pane.getVerticalScrollBar().setValue(pane.getVerticalScrollBar().getMaximum());
            check(!wheel(pane,1).isConsumed(),"lower boundary does not trap input");
            pane.scrollToTop();wheel(pane,.01);pane.scrollToTop();
            for(int i=0;i<100;i++)wheel(pane,.01);
            check(pane.getVerticalScrollBar().getValue()==18,"top navigation clears a partial-pixel remainder");
            pane.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);pane.doLayout();pane.getViewport().doLayout();
            wheel(pane,1,InputEvent.SHIFT_DOWN_MASK,MouseWheelEvent.WHEEL_UNIT_SCROLL);
            check(pane.getHorizontalScrollBar().getValue()==18,"Shift wheel also matches PDF scale");
            pane.removeNotify();
        });
        System.out.println("QuizScrollMotionTest passed: "+checks+" shared PDF distance, precision, boundary handoff and navigation checks. No windows or timers.");
    }
}
