package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Isolated weekly-v interaction/persistence checks. Never opens a native window or uses personal data. */
public final class PlannerWeeklyVTest {
    static int checks;
    static final Clock CLOCK=Clock.fixed(Instant.parse("2026-10-14T04:00:00Z"),ZoneId.of("Asia/Seoul"));
    static final LocalDate MONDAY=LocalDate.of(2026,10,12),TODAY=LocalDate.of(2026,10,14);
    static final Path OUT=Path.of("tmp/weekly-v-20261018");
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);Path root=Files.createTempDirectory("synesis-weekly-v-");PlannerStore store=new PlannerStore(root.resolve("planner.json"));
        store.saveTags(List.of(),List.of(new Tag("course","수업")));store.saveTodoTags(List.of(),List.of(new Tag("todo-course","수업"),new Tag("todo-dev","개발"),new Tag("todo-personal","개인")));
        String[] titles={"영어 수업","스페인어","전시 관람","한국사","현대예술의 이해","카페 공부","주간 정리"};int[] starts={9,10,8,9,10,11,10};
        for(int d=0;d<7;d++){int length=d==2||d==5?3:2;LocalDateTime start=MONDAY.plusDays(d).atTime(starts[d],0);store.saveEvent(new Event("event-"+d,titles[d],"",start,start.plusHours(length),false,EventColor.values()[d%6],List.of("course"),false,Repeat.NONE,-1));}
        for(int d=0;d<7;d++){LocalDateTime start=MONDAY.plusDays(d).atTime(d==0?13:d==2?13:18,0);store.saveEvent(new Event("later-"+d,new String[]{"C++ 과제","저녁 약속","프로젝트 개발","친구 모임","금융의 이해","개발 스프린트","자유 시간"}[d],"",start,start.plusHours(2),false,EventColor.values()[(d+4)%6],List.of(),false,Repeat.NONE,-1));}
        store.saveTask(new Task("daily-1","전시 관람",TODAY,"미술관 가서 보고 오기..",false));store.saveTask(new Task("daily-2","점심 식사",TODAY,"동기랑 밥약 1학",true));store.saveTask(new Task("daily-3","프로젝트 개발",TODAY,"시네시스완성하기..",false));store.saveTask(new Task("daily-4","스페인어 복습",TODAY,"진짜 해야됨.",false));
        for(int i=0;i<6;i++)store.saveWeeklyTask(new WeeklyTask("todo-"+i,new String[]{"C++ 연습문제 제출","스페인어 문화 과제","현대예술 전시 에세이","한국사 시험 범위 정리","Synesis PDF 모듈 개선","운동 3회 이상 가기"}[i],MONDAY.plusDays(i),TODAY,List.of(i<3?"todo-course":i<5?"todo-dev":"todo-personal"),i<2));
        store.saveWeeklyGoal(new WeeklyGoal("goal-1","러닝 뛰고 오기",TODAY,5,3));store.saveWeeklyGoal(new WeeklyGoal("goal-2","헬스 개빡세게 하기",TODAY,3,2));store.saveWeeklyGoal(new WeeklyGoal("goal-3","개발 스프린트 (20시간)",TODAY,20,12));
        byte[] fileBeforeRender=Files.readAllBytes(store.file());
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign p=new PlannerDesign(store,CLOCK);p.setSize(1430,844);layout(p);PlannerWeekView view=p.weeklyView;
            check(p.weeklyView.isVisible()&&!p.monthly,"weekly-v is the default screen");check(view.weekTasks().size()==6,"deadline does not remove overdue weekly TODOs");check(p.state.events().size()==14,"daily and weekly TODOs are independent of events");
            check(view.dailyRows.getComponentCount()==4&&view.goalRows.getComponentCount()==3,"all daily TODOs and multiple weekly goals visible");
            check(view.mini.getBounds().equals(new Rectangle(1114,112,288,232)),"mini-calendar keeps the original header spacing");check(p.calendar.getBounds().equals(new Rectangle(28,112,1066,496)),"navigation does not reserve extra header space");
            check(view.daily.getBounds().equals(new Rectangle(28,624,468,192)),"Figma daily TODO slot");check(view.quick.getBounds().equals(new Rectangle(512,624,582,192)),"Figma Quick Note slot");
            PlannerCalendar cal=(PlannerCalendar)p.calendar.getComponent(0);PlannerCalendar.Week week=(PlannerCalendar.Week)cal.getComponent(0);PlannerCalendar.WeekBody body=week.body;
            check(body.minuteY(60)-body.minuteY(0)==28,"Figma one-hour row height is preserved");
            check(Math.abs(p.weeklyScrollMinute-420)<2,"default starts at 07:00");
            render(p,"weekly-v.png");check(Arrays.equals(fileBeforeRender,Files.readAllBytes(store.file())),"viewing and rendering never save example data");
            ((JButton)view.filters.getComponent(2)).doClick();check(view.todoRows.getComponentCount()==2,"weekly TODO tag filter uses its own membership");((JButton)view.filters.getComponent(0)).doClick();
            PlannerWeekView.TodoRow weeklyRow=(PlannerWeekView.TodoRow)view.todoRows.getComponent(2);weeklyRow.check.doClick();layout(p);check(store.load().weeklyTasks().get(2).completed(),"weekly TODO check persists completion");
            PlannerWeekView.TodoRow row=(PlannerWeekView.TodoRow)view.dailyRows.getComponent(0);row.active(true);check(row.edit.isVisible(),"TODO pencil appears on hover");check(SwingUtilities.getDeepestComponentAt(row,row.getWidth()-10,10)==row.edit,"pencil remains a reachable hit target");
            PlannerWeekView.GoalRow goal=(PlannerWeekView.GoalRow)view.goalRows.getComponent(0);goal.active(true);check(goal.plus.isVisible()&&goal.minus.isVisible()&&goal.edit.isVisible(),"goal hover controls appear together");render(p,"weekly-v-hover.png");row.active(false);check(!row.edit.isVisible(),"TODO pencil hides after hover");
            goal.plus.doClick();check(store.load().weeklyGoals().get(0).completed()==4,"native goal plus button persists progress");
            p.accept(store.adjustWeeklyGoal("goal-1",100));goal=(PlannerWeekView.GoalRow)view.goalRows.getComponent(0);goal.active(true);check(!goal.plus.isEnabled(),"plus is disabled at target");check(store.load().weeklyGoals().get(0).completed()==5,"store clamps goal to target");
            p.accept(store.adjustWeeklyGoal("goal-1",-100));goal=(PlannerWeekView.GoalRow)view.goalRows.getComponent(0);goal.active(true);check(!goal.minus.isEnabled()&&store.load().weeklyGoals().get(0).completed()==0,"minus is disabled and clamped at zero");
            PlannerWeekEditors.Daily daily=new PlannerWeekEditors.Daily(p,p.state.tasks().get(0));daily.title.setText("새로운 하루 TODO");daily.detail.setText("여러 줄\n설명");daily.date.setDate(TODAY.plusDays(1));daily.save();check(store.load().tasks().get(0).date().equals(TODAY.plusDays(1)),"daily editor changes date and description");
            p.navigateTasks(1);check(view.dailyRows.getComponentCount()==1&&p.taskDate.equals(TODAY.plusDays(1))&&p.anchor.equals(TODAY),"daily navigation is independent from the selected calendar week");
            PlannerWeekEditors.Todo todo=new PlannerWeekEditors.Todo(p,p.state.weeklyTasks().get(0));check(todo.state.todoTags().size()==3&&todo.state.tags().size()==1,"TODO editor uses separate tag namespace");
            todo.title.setText("수정한 주간 TODO");todo.week.setDate(MONDAY.plusWeeks(1));todo.deadline.setDate(MONDAY.plusWeeks(1).plusDays(1));todo.selected.add("todo-dev");todo.save();check(store.load().weeklyTasks().get(0).tagIds().size()==2,"TODO accepts multiple tags");check(view.weekTasks().size()==5,"moving TODO week changes membership, deadline does not");
            p.navigate(1);check(view.weekTasks().size()==1,"TODO follows its selected week");
            todo=new PlannerWeekEditors.Todo(p,null);todo.title.setText("");long revision=store.load().revision();todo.save();check(!todo.error.getText().isEmpty()&&store.load().revision()==revision,"invalid draft does not write");
            PlannerWeekEditors.GoalEditor editGoal=new PlannerWeekEditors.GoalEditor(p,p.state.weeklyGoals().get(1));editGoal.title.setText("다음 주 운동");editGoal.week.setDate(MONDAY.plusWeeks(1));editGoal.target.setValue(1);editGoal.save();check(store.load().weeklyGoals().get(1).completed()==1,"reducing target clamps existing progress");
            check(store.load().weeklyGoals().get(1).week().equals(MONDAY.plusWeeks(1)),"goal can move to another week");
            PlannerWeekEditors.Todo cancel=new PlannerWeekEditors.Todo(p,null);cancel.title.setText("저장하지 않는 TODO");int count=store.load().weeklyTasks().size();PlannerDialogs.requestClose(cancel);check(store.load().weeklyTasks().size()==count,"cancel never saves unfinished TODO");
            PlannerDialogs.TagEditor todoTags=new PlannerDialogs.TagEditor(store,p.state,Set.of(),(s,ids)->p.accept(s),true);todoTags.newName.setText("독서");todoTags.create();todoTags.names.get("todo-course").setText("강의");todoTags.save();check(store.load().todoTags().size()==4&&store.load().tags().size()==1&&store.load().tags().get(0).name().equals("수업"),"TODO tag editor creates and renames without altering event tags");
            check(store.load().todoTags().get(0).name().equals("강의"),"TODO tag editor persists names with stable IDs");
            p.anchor=TODAY;p.taskDate=TODAY;p.refresh();layout(p);renderForm(p,new PlannerWeekEditors.Daily(p,null),480,470,"daily-editor.png");renderForm(p,new PlannerWeekEditors.Todo(p,null),480,560,"weekly-todo-editor.png");renderForm(p,new PlannerWeekEditors.GoalEditor(p,null),480,430,"weekly-goal-editor.png");
            p.month.doClick();layout(p);check(p.monthly&&!p.weeklyView.isVisible()&&p.calendar.getParent()==p,"monthly keeps its existing view and calendar parent");p.week.doClick();layout(p);check(!p.monthly&&p.calendar.getParent()==view,"weekly/monthly switches keep the single calendar host");
            for(int width:new int[]{1430,1100,900,680,480,360}){JScrollPane scroll=new JScrollPane(p);scroll.setSize(width,650);for(int pass=0;pass<4;pass++)layout(scroll);check(p.getWidth()==scroll.getViewport().getWidth(),"weekly fits viewport width "+width);check(view.goals.getY()+view.goals.getHeight()<=p.getHeight(),"weekly sidebar remains reachable at "+width);
                if(width>=680)check(Math.abs(view.today.getX()+view.today.getWidth()/2-(p.calendar.getX()+p.calendar.getWidth()/2))<=1,"navigation stays centered above the calendar at "+width);
                check(view.range.getY()-(view.title.getY()+view.title.getHeight())==3,"original title/date gap is unchanged at "+width);
                check(p.calendar.getY()==view.title.getY()+1+(p.getWidth()-(p.getWidth()<900?32:56)<940?132:84),"navigation cannot increase the original header height at "+width);
                if(width>=900)check(Math.abs(view.today.getY()+view.today.getHeight()/2.0-((view.range.getY()+view.range.getHeight()+p.calendar.getY())/2.0-8))<=.5,"navigation is eight pixels above the date/calendar midpoint at "+width);
                List<Component> controls=List.of(view.range,view.previous,view.today,view.next,view.switcher,view.add,view.bell);
                for(int a=0;a<controls.size();a++)for(int b=a+1;b<controls.size();b++)check(!controls.get(a).getBounds().intersects(controls.get(b).getBounds()),"header controls do not overlap at "+width);
                for(JButton nav:List.of(view.previous,view.today,view.next))check(nav.getHeight()>=25&&nav.getY()+nav.getHeight()/2.0<p.calendar.getY(),"navigation center remains above the calendar top line at "+width);
            }
            p.setSize(1430,844);p.anchor=TODAY;p.refresh();layout(p);week=(PlannerCalendar.Week)((PlannerCalendar)p.calendar.getComponent(0)).getComponent(0);week.timeline.getViewport().setViewPosition(new Point(0,0));render(p,"weekly-v-top.png");week.timeline.getVerticalScrollBar().setValue(week.timeline.getVerticalScrollBar().getMaximum());render(p,"weekly-v-bottom.png");
        }catch(Exception e){throw new RuntimeException(e);}});
        State restarted=new PlannerStore(store.file()).load();check(restarted.weeklyTasks().size()==6&&restarted.weeklyGoals().size()==3,"weekly data survives restart");
        store.saveTags(restarted.tags(),List.of(new Tag("course","일정 태그 이름 변경")));check(store.load().todoTags().get(0).name().equals("강의"),"event tag edits do not change TODO tags");
        State before=store.load();store.saveTodoTags(before.todoTags(),List.of(new Tag("todo-course","강의"),new Tag("todo-personal","개인")));State after=store.load();check(after.weeklyTasks().get(0).tagIds().equals(List.of("todo-course")),"deleting TODO tag removes only its links");check(after.events().equals(before.events())&&after.tasks().equals(before.tasks()),"TODO tag edits preserve events and daily TODOs");
        PlannerStore legacy=new PlannerStore(root.resolve("legacy.json"));Files.writeString(legacy.file(),"{\"format\":\"synesis-planner\",\"version\":1,\"state\":{\"revision\":2,\"events\":[],\"tags\":[],\"tasks\":[],\"goals\":[{\"period\":\"week:2026-10-12\",\"title\":\"옛 주간 목표\",\"target\":3,\"completed\":2},{\"period\":\"month:2026-10\",\"title\":\"월간 목표\",\"target\":10,\"completed\":3}],\"notificationsEnabled\":false,\"deliveredReminders\":[]}}");
        State old=legacy.load();check(old.weeklyGoals().size()==1&&old.weeklyGoals().get(0).completed()==2,"legacy weekly goal remains available");legacy.deleteWeeklyGoal(old.weeklyGoals().get(0).id());check(legacy.load().weeklyGoals().isEmpty()&&legacy.load().goals().size()==2,"deleted migrated weekly goal does not reappear or change monthly data");
        System.out.println("PASS: "+checks+" weekly-v interaction, persistence and responsive checks; renders: "+OUT.toAbsolutePath());
    }
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested&&child.isVisible())layout(nested);}
    static void render(PlannerDesign p,String name)throws Exception{layout(p);BufferedImage image=new BufferedImage(p.getWidth(),p.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();p.printAll(g);g.dispose();ImageIO.write(image,"png",OUT.resolve(name).toFile());}
    static void renderForm(PlannerDesign p,JPanel form,int width,int height,String name)throws Exception{form.setSize(width,height);layout(form);BufferedImage image=new BufferedImage(width,height,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();form.printAll(g);g.dispose();ImageIO.write(image,"png",OUT.resolve(name).toFile());}
}
