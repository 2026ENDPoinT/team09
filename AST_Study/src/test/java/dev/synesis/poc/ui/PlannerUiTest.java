package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.*;
import javax.imageio.ImageIO;
import javax.swing.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Exercises native controls and renders all six requested views without opening windows. */
public final class PlannerUiTest {
    static int checks;static Path output=Path.of("build/planner-verification-20261018");
    static void check(boolean condition,String message){checks++;if(!condition)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planner-ui-");System.setProperty("synesis.dataRoot",root.toString());
        Clock clock=Clock.fixed(Instant.parse("2026-10-17T03:00:00Z"),ZoneId.of("Asia/Seoul"));PlannerStore store=new PlannerStore();
        Tag exam=new Tag("exam","시험"),math=new Tag("math","미적");store.saveTags(List.of(),List.of(exam,math));
        for(int d=0;d<7;d++){LocalDate date=LocalDate.of(2026,10,12).plusDays(d);int hour=new int[]{9,10,9,11,10,13,14}[d];String title=new String[]{"경영학개론","컴퓨터사고","경영학개론","데이터 분석","금융강의 복습","중간고사 준비","다음 주 계획"}[d];store.saveEvent(new Event("fixture-"+d,title,"",date.atTime(hour,0),date.atTime(hour,0).plusMinutes(d==1||d==4||d==5?120:90),false,EventColor.NAVY,List.of(),d==5,Repeat.NONE,-1));}
        for(int d:new int[]{0,2}){LocalDate date=LocalDate.of(2026,10,12).plusDays(d);store.saveEvent(new Event("second-"+d,d==0?"재무관리":"팀 프로젝트","",date.atTime(d==0?14:13,0),date.atTime(d==0?15:14,30),false,EventColor.NAVY,List.of(),false,Repeat.NONE,-1));}
        store.saveTask(new Task("t1","재무제표 개념 복습",LocalDate.now(clock),"금융강의 · 30분",true));store.saveTask(new Task("t2","중간고사 예상 문제 풀기",LocalDate.now(clock),"오늘 오후 1시",false));store.saveTask(new Task("t3","팀 프로젝트 자료 모으기",LocalDate.now(clock),"오늘까지",false));
        Event sample=new Event("sample","미적분 중간고사","3–6장 복습 · 공학용 계산기와 학생증 챙기기",LocalDateTime.of(2026,10,22,10,0),LocalDateTime.of(2026,10,22,11,30),false,EventColor.NAVY,List.of("exam","math"),true,Repeat.NONE,10);
        store.saveGoal(new Goal("week:2026-10-12","금융강의 3개 복습하기",3,2));store.saveGoal(new Goal("month:2026-10","금융강의 12개 복습하기",12,8));Files.createDirectories(output);
        AtomicReference<PlannerDesign> ref=new AtomicReference<>();SwingUtilities.invokeAndWait(()->{PlannerDesign p=new PlannerDesign(store,clock);p.setSize(1430,844);layout(p);ref.set(p);});SwingUtilities.invokeAndWait(()->{});
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign p=ref.get();layout(p);check(!p.bell.isEnabled()&&p.bell.getActionListeners().length==1,"notification entry stays inactive");renderScreen(p,null,null,"weekly");check(p.range.getText().equals("2026년 10월 12일 — 18일"),"week range");p.next.doClick();check(p.range.getText().contains("19일"),"next week action");p.today.doClick();check(p.anchor.equals(LocalDate.now(clock)),"today action");
            p.month.doClick();check(p.monthly&&p.range.getText().equals("2026년 10월"),"month action");renderScreen(p,null,null,"monthly");p.anchor=LocalDate.of(2026,8,31);p.refresh();PlannerCalendar cal=(PlannerCalendar)p.calendar.getComponent(0);check(((PlannerCalendar.Month)cal.getComponent(0)).rows==6,"six week month");p.anchor=LocalDate.of(2021,2,1);p.refresh();cal=(PlannerCalendar)p.calendar.getComponent(0);check(((PlannerCalendar.Month)cal.getComponent(0)).rows==4,"four week month");p.today.doClick();
            for(boolean monthly:new boolean[]{false,true}){p.setMonthly(monthly);PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,p.state,null,sample.start(),p::accept,clock);editor.title.setText(sample.title());editor.description.setText(sample.description());editor.endTime.setSelectedItem("11:30");editor.selected.addAll(sample.tagIds());editor.important.setSelected(true);editor.renderTags();layoutSize(editor,920,804);renderScreen(p,editor,null,monthly?"monthly-add":"weekly-add");PlannerDialogs.TagEditor tags=new PlannerDialogs.TagEditor(store,p.state,editor.selected,(s,ids)->{});tags.newName.setText("물리");layoutSize(tags,440,536);renderScreen(p,editor,tags,monthly?"monthly-tags":"weekly-tags");
                check(!editor.reminder.isEnabled()&&editor.draft().reminderMinutes()==-1,"new event has no active reminder");check(editor.draft().start().equals(sample.start()),"date/time input produces real local date");check(editor.draft().tagIds().size()==2,"selected tags in event draft");editor.swatches.get(1).doClick();check(editor.draft().color()==EventColor.BLUE,"color choice changes draft");BufferedImage colorRender=new BufferedImage(920,804,BufferedImage.TYPE_INT_RGB);Graphics2D colorGraphics=colorRender.createGraphics();editor.printAll(colorGraphics);colorGraphics.dispose();editor.allDay.setSelected(true);editor.syncTime();Event allDay=editor.draft();check(allDay.start().toLocalTime().equals(LocalTime.MIDNIGHT)&&allDay.end().equals(LocalDateTime.of(2026,10,23,0,0)),"inclusive all-day end converted to exclusive midnight");editor.allDay.setSelected(false);editor.endTime.setSelectedItem("09:00");try{editor.draft();throw new AssertionError("invalid duration accepted");}catch(IllegalArgumentException expected){checks++;}
                check(store.load().events().stream().noneMatch(e->e.title().equals(sample.title())),"rendering and editing never save unfinished event");}
            PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,p.state,null,sample.start(),p::accept,clock);AtomicInteger closes=new AtomicInteger();editor.putClientProperty("planner.close",(Runnable)closes::incrementAndGet);editor.save();check(closes.get()==0&&editor.error.getForeground().equals(PlannerStyle.ERROR_COLOR),"empty title reports validation without closing");editor.title.setText("저장 확인");editor.save();check(closes.get()==1&&store.load().events().stream().anyMatch(e->e.title().equals("저장 확인")),"save commits exactly once and closes");
            PlannerDialogs.TagEditor tags=new PlannerDialogs.TagEditor(store,p.state,Set.of("exam"),(s,ids)->p.accept(s));tags.newName.setText("물리");tags.create();check(tags.selected.size()==2,"new tag selected immediately");tags.names.get("exam").setText("중간고사");tags.save();check(store.load().tags().stream().anyMatch(t->t.name().equals("중간고사")),"tag rename saves stable ID");
            p.week.doClick();JCheckBox task=findCheck(p,"중간고사 예상 문제 풀기 완료");task.doClick();check(store.load().tasks().stream().filter(t->t.id().equals("t2")).findFirst().orElseThrow().completed(),"task check updates shared store");
            // Two overlapping events must remain separate native hit targets.
            State s=store.load();Event overlap=new Event("overlap","겹친 일정","",LocalDateTime.of(2026,10,12,9,30),LocalDateTime.of(2026,10,12,11,0),false,EventColor.ROSE,List.of(),false,Repeat.NONE,-1);p.accept(store.saveEvent(overlap));layout(p);PlannerCalendar pc=(PlannerCalendar)p.calendar.getComponent(0);PlannerCalendar.WeekBody body=findBody(pc);List<JButton> same=body.positions.entrySet().stream().filter(e->e.getValue().day()==0&&e.getValue().start()<700).map(Map.Entry::getKey).toList();check(same.size()==2&&!same.get(0).getBounds().intersects(same.get(1).getBounds()),"overlapping events get distinct columns");
            p.setSize(1180,824);layout(p);check(p.calendar.getWidth()>700&&p.tasks.getX()+p.tasks.getWidth()<=p.getWidth()-37,"minimum width layout");
            PlannerDialogs.EventEditor dates=new PlannerDialogs.EventEditor(store,p.state,null,LocalDateTime.of(2026,10,18,10,0),p::accept,clock);dates.title.setText("날짜 조정 확인");
            dates.startDate.setDate(LocalDate.of(2026,10,22));check(dates.draft().end().equals(LocalDateTime.of(2026,10,22,11,0)),"moving start past end advances the displayed end date while retaining its time");
            dates.endDate.setDate(LocalDate.of(2026,10,18));check(dates.endDate.date().equals(dates.startDate.date()),"entering an end date before start also clamps end to start");
            dates.endDate.setDate(LocalDate.of(2026,10,25));dates.startDate.setDate(LocalDate.of(2026,10,23));check(dates.endDate.date().equals(LocalDate.of(2026,10,25)),"valid multi-day end date stays intact");
            LocalDate current=LocalDate.now(clock),calendarDate=p.anchor;
            p.accept(store.saveTask(new Task("previous-day","어제 완료한 할 일",current.minusDays(1),"",true)));
            p.previousTaskDay.doClick();check(p.taskDate.equals(current.minusDays(1))&&p.taskCount.getText().equals("1 / 1개 완료"),"task card previous arrow filters date and completed count");
            check(findCheck(p.taskRows,"어제 완료한 할 일 완료")!=null&&p.anchor.equals(calendarDate),"task date navigation does not move the main calendar");
            p.accept(store.load());check(p.taskDate.equals(current.minusDays(1)),"refresh keeps selected task day");
            p.nextTaskDay.doClick();check(p.taskDate.equals(current)&&p.taskHeading.getText().startsWith("오늘"),"returning to current day restores Today label");
            p.nextTaskDay.doClick();check(p.taskDate.equals(current.plusDays(1))&&!p.taskHeading.getText().contains("오늘")&&p.taskCount.getText().equals("0 / 0개 완료"),"next day displays its own date and empty task state");
            p.previousTaskDay.doClick();
            dates.allDay.doClick();dates.startDate.setDate(LocalDate.of(2026,10,27));check(dates.endDate.date().equals(LocalDate.of(2026,10,27))&&dates.draft().end().equals(LocalDateTime.of(2026,10,28,0,0)),"all-day automatic adjustment keeps the inclusive displayed end date");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" planner UI checks; six renders in "+output.toAbsolutePath());
    }
    static PlannerCalendar.WeekBody findBody(Container c){for(Component child:c.getComponents()){if(child instanceof PlannerCalendar.WeekBody body)return body;if(child instanceof Container nested){var result=findBody(nested);if(result!=null)return result;}}return null;}
    static JCheckBox findCheck(Container c,String name){for(Component child:c.getComponents()){if(child instanceof JCheckBox b&&name.equals(b.getName()))return b;if(child instanceof Container nested){var r=findCheck(nested,name);if(r!=null)return r;}}return null;}
    static void layoutSize(JComponent c,int w,int h){c.setSize(w,h);layout(c);}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    static void renderScreen(PlannerDesign planner,JPanel editor,JPanel tags,String name)throws Exception {
        BufferedImage image=new BufferedImage(1600,900,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,1600,900);JPanel header=LibraryDesign.header(()->{});layoutSize(header,1600,56);header.printAll(g);LibrarySidebar sidebar=new LibrarySidebar(()->false,()->true,()->{},()->{},()->{});layoutSize(sidebar,170,844);Graphics2D side=(Graphics2D)g.create(0,56,170,844);sidebar.printAll(side);side.dispose();layoutSize(planner,1430,844);Graphics2D main=(Graphics2D)g.create(170,56,1430,844);planner.printAll(main);main.dispose();
        if(editor!=null){g.setColor(new Color(0,6,18,46));g.fillRect(0,0,1600,900);Graphics2D dialog=(Graphics2D)g.create(340,48,920,804);editor.printAll(dialog);dialog.dispose();}if(tags!=null){g.setColor(new Color(0,6,18,64));g.fillRect(0,0,1600,900);Graphics2D dialog=(Graphics2D)g.create(580,182,440,536);tags.printAll(dialog);dialog.dispose();}g.dispose();ImageIO.write(image,"png",output.resolve(name+".png").toFile());
    }
}
