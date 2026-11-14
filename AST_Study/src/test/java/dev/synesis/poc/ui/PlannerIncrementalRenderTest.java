package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import static dev.synesis.poc.planner.PlannerModel.*;
import javax.swing.*;
import java.awt.*;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import java.util.Set;

/** Region invalidation and stable geometry, entirely offscreen with an isolated store. */
public final class PlannerIncrementalRenderTest {
    static int checks;
    public static void main(String[] args)throws Exception{
        Path file=Files.createTempDirectory("planner-incremental-").resolve("planner.json");
        Clock clock=Clock.fixed(Instant.parse("2026-10-28T03:00:00Z"),ZoneId.of("Asia/Seoul"));LocalDate day=LocalDate.now(clock),week=weekStart(day);
        PlannerStore store=new PlannerStore(file);
        State state=new State(1,List.of(new PlannerModel.Event("early","이른 일정","",week.atTime(1,0),week.atTime(2,0),false,EventColor.BLUE,List.of(),false,Repeat.WEEKLY,-1),new PlannerModel.Event("late","늦은 일정","",week.plusDays(1).atTime(22,0),week.plusDays(1).atTime(23,0),false,EventColor.ROSE,List.of(),false,Repeat.DAILY,-1)),List.of(),List.of(new Task("daily","오늘 할 일",day,"설명",false)),List.of(),false,Set.of(),List.of(new WeeklyTask("todo","이번 주 할 일",day,week,List.of("tag"),false)),List.of(new Tag("tag","공부")),List.of(new WeeklyGoal("goal","목표",week,5,0)));
        SwingUtilities.invokeAndWait(()->{
            PlannerDesign p=new PlannerDesign(store,clock);
            try{
                p.accept(state);p.setSize(1430,900);for(int i=0;i<4;i++)layout(p);
                var v=p.weeklyView;Component daily=v.dailyRows.getComponent(0),todo=v.todoRows.getComponent(0),goal=v.goalRows.getComponent(0),mini=v.dates.getComponent(8),calendar=p.calendar.getComponent(0);
                p.refresh();check(v.dailyRows.getComponent(0)==daily&&v.todoRows.getComponent(0)==todo&&v.goalRows.getComponent(0)==goal&&v.dates.getComponent(8)==mini,"unchanged refresh recreated components");
                State goals=new State(2,state.events(),state.tags(),state.tasks(),state.goals(),false,Set.of(),state.weeklyTasks(),state.todoTags(),List.of(new WeeklyGoal("goal","목표",week,5,1)));
                p.accept(goals);check(v.dailyRows.getComponent(0)==daily&&v.todoRows.getComponent(0)==todo&&v.dates.getComponent(8)==mini&&p.calendar.getComponent(0)==calendar,"goal edit invalidated unrelated regions");check(v.goalRows.getComponent(0)!=goal,"goal edit was not rendered");
                State tasks=new State(3,state.events(),state.tags(),List.of(state.tasks().get(0).toggle()),state.goals(),false,Set.of(),state.weeklyTasks(),state.todoTags(),goals.weeklyGoals());
                p.accept(tasks);check(v.dailyRows.getComponent(0)!=daily&&v.todoRows.getComponent(0)==todo&&v.dates.getComponent(8)==mini,"daily task edit invalidation");
                p.navigateTasks(1);check(v.day.getText().startsWith("10월 29일")&&v.dailyRows.getComponentCount()==1,"task date navigation");
                v.moveMini(1);Component moved=v.dates.getComponent(8);p.accept(new State(4,tasks.events(),tasks.tags(),tasks.tasks(),tasks.goals(),false,Set.of("receipt"),tasks.weeklyTasks(),tasks.todoTags(),tasks.weeklyGoals()));check(v.dates.getComponent(8)==moved,"receipt/revision reset mini-calendar navigation");
                v.tagFilter="tag";v.renderTodos();p.accept(new State(5,tasks.events(),tasks.tags(),tasks.tasks(),tasks.goals(),false,Set.of(),List.of(),tasks.todoTags(),tasks.weeklyGoals()));check(v.tagFilter.isEmpty(),"removed tag filter did not reset");
                p.accept(state);p.taskDate=day;p.anchor=day;p.refresh();for(int i=0;i<4;i++)layout(p);
                PlannerCalendar.Week w=(PlannerCalendar.Week)((PlannerCalendar)p.calendar.getComponent(0)).getComponent(0);
                int[] events={0};w.timeline.getViewport().addChangeListener(e->events[0]++);Meter meter=new Meter();RepaintManager previous=RepaintManager.currentManager(p);RepaintManager.setCurrentManager(meter);
                try{
                    for(int i=0;i<50;i++){w.timeline.doLayout();w.updateIndicators();}
                    check(events[0]==0,"unchanged layout changed viewport bounds");check(meter.dirty==0,"unchanged layout/indicators requested repaint");
                    for(int y:new int[]{0,200,600,1200}){
                        w.timeline.getViewport().setViewPosition(new Point(0,y));w.updateIndicators();
                        for(JButton badge:w.edgeBadges){int d=(int)badge.getClientProperty("planner.edgeDay");boolean above=Boolean.TRUE.equals(badge.getClientProperty("planner.edgeAbove"));int count=w.hidden(d,above).size();check(badge.getText().equals((above?"위":"아래")+"에 일정 "+count+"개가 있어요!"),"hidden indicator count differs after scroll");}
                    }
                    p.setSize(1120,824);for(int i=0;i<4;i++)layout(p);check(w.timeline.getViewport().getWidth()>0&&w.body.getWidth()==w.timeline.getViewport().getWidth(),"resize lost overlay viewport width");
                }finally{RepaintManager.setCurrentManager(previous);}
                p.setMonthly(true);for(int i=0;i<4;i++)layout(p);Component upcoming=p.upcomingRows.getComponent(0),task=p.taskRows.getComponent(0);p.accept(goals);check(p.upcomingRows.getComponent(0)==upcoming&&p.taskRows.getComponent(0)==task,"monthly goal edit recreated tasks/upcoming");
                p.readFailed=true;p.writeEnabled(false);p.accept(goals);check(p.add.isEnabled()&&p.addTask.isEnabled()&&p.weeklyView.addGoal.isEnabled(),"same-data recovery left controls disabled");
                p.setMonthly(false);p.setVisible(false);check(!p.refreshTimer.isRunning(),"hidden refresh timer");p.setVisible(true);check(p.calendar.getComponentCount()==1,"show lost calendar");
            }finally{p.dispose();}
        });
        System.out.println("PlannerIncrementalRenderTest passed: "+checks+" checks");System.exit(0);
    }
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
    static final class Meter extends RepaintManager{@Override public void addDirtyRegion(JComponent c,int x,int y,int w,int h){if(w>0&&h>0)dirty++;}long dirty;}
}
