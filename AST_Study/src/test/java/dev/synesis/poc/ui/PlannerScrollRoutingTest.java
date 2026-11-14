package dev.synesis.poc.ui;

import dev.synesis.poc.planner.PlannerStore;
import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.nio.file.Files;
import java.time.*;

/** Empty/fitting cards yield the wheel to the screen; overflowing cards keep their own scroll. */
public final class PlannerScrollRoutingTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static MouseWheelEvent wheel(JScrollPane target,double rotation){
        MouseWheelEvent e=new MouseWheelEvent(target,MouseWheelEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,50,50,50,50,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,rotation<0?-1:1,rotation);
        target.dispatchEvent(e);return e;
    }
    public static void main(String[] args)throws Exception{
        var store=new PlannerStore(Files.createTempDirectory("planner-scroll-routing-").resolve("planner.json"));
        SwingUtilities.invokeAndWait(()->{
            var planner=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-19T03:00:00Z"),ZoneId.of("Asia/Seoul")));
            UnifiedScrollPane screen=new UnifiedScrollPane(planner);screen.setSize(1100,500);PlannerWeekOverviewTest.layout(screen);
            var v=planner.weeklyView;
            for(JScrollPane card:new JScrollPane[]{v.todoScroll,v.goalScroll,v.dailyScroll,v.filterScroll}){
                screen.getVerticalScrollBar().setValue(0);
                check(card.getViewport().getViewSize().height<=card.getViewport().getHeight(),"empty card has no inner overflow");
                MouseWheelEvent e=wheel(card,1);
                check(screen.getVerticalScrollBar().getValue()>0&&card.getVerticalScrollBar().getValue()==0,"empty/fitting card scrolls whole screen");
                check(e.isConsumed(),"forwarded event handled once");
            }
            double[] precise={0};screen.addWheelInputListener(e->precise[0]=e.getPreciseWheelRotation());wheel(v.todoScroll,.35);
            check(precise[0]==.35,"trackpad precision retained when forwarding");
            v.todoRows.removeAll();for(int i=0;i<40;i++){JLabel row=new JLabel("긴 TODO "+i);row.setPreferredSize(new Dimension(180,30));row.setMaximumSize(new Dimension(Integer.MAX_VALUE,30));v.todoRows.add(row);}v.todoRows.revalidate();PlannerWeekOverviewTest.layout(screen);
            check(v.todoScroll.getViewport().getViewSize().height>v.todoScroll.getViewport().getHeight(),"many TODOs create actual inner overflow");
            int outerY=screen.getVerticalScrollBar().getValue();wheel(v.todoScroll,1);
            check(v.todoScroll.getVerticalScrollBar().getValue()>0&&screen.getVerticalScrollBar().getValue()==outerY,"overflowing TODO list scrolls internally");
            v.todoScroll.getVerticalScrollBar().setValue(v.todoScroll.getVerticalScrollBar().getMaximum());wheel(v.todoScroll,1);
            check(screen.getVerticalScrollBar().getValue()>outerY,"list endpoint continues the same gesture on the outer screen");
            v.todoRows.removeAll();v.todoRows.add(new JLabel("한 개의 TODO"));v.todoRows.revalidate();PlannerWeekOverviewTest.layout(screen);screen.getVerticalScrollBar().setValue(0);wheel(v.todoScroll,1);
            check(screen.getVerticalScrollBar().getValue()>0,"shrinking list immediately returns scrolling to screen");
        });
        System.out.println("PASS: "+checks+" planner nested-scroll checks");
    }
}
