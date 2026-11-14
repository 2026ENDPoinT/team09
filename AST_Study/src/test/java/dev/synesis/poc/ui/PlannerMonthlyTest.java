package dev.synesis.poc.ui;

import com.google.gson.*;
import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Disposable data, no native windows or provider calls. Checks new month ownership and shared UI wiring. */
public final class PlannerMonthlyTest {
    static int checks;
    static final LocalDate NOW=LocalDate.of(2026,11,2);
    static final Clock CLOCK=Clock.fixed(NOW.atTime(12,0).atZone(ZoneId.of("Asia/Seoul")).toInstant(),ZoneId.of("Asia/Seoul"));
    static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    public static void main(String[] args)throws Exception{
        Path temp=Files.createTempDirectory("synesis-monthly-");System.setProperty("synesis.dataRoot",temp.resolve("data").toString());
        storeContracts(new PlannerStore(temp.resolve("store.json")));
        PlannerStore store=new PlannerStore(temp.resolve("ui.json"));fixtures(store);
        SwingUtilities.invokeAndWait(()->{try{scrollHints();ui(store);}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" monthly storage, selection, TODO, span, responsiveness and asset checks");System.exit(0);
    }
    static void storeContracts(PlannerStore store)throws Exception{
        Tag tag=new Tag("tag","수업");store.saveTodoTags(List.of(),List.of(tag));
        MonthlyTask month=new MonthlyTask("month","이번 달 과제",null,NOW,List.of("tag"),false);store.saveMonthlyTask(month);
        check(store.load().monthlyTasks().get(0).month().equals(NOW.withDayOfMonth(1)),"month normalizes independently of optional deadline");
        WeeklyTask weekly=new WeeklyTask("week","이번 주 과제",null,NOW,List.of("tag"),false);store.saveWeeklyTask(weekly);store.toggleWeeklyTask("week");
        store.saveTask(new Task("daily","일별 과제",NOW,"",false));store.toggleTask("daily");
        Event event=event("e","일정",NOW,9,EventColor.BLUE,false);store.saveEvent(event);store.saveGoal(new Goal("month:2026-11","월간 목표",5,2));
        store.saveWeeklyGoal(new WeeklyGoal("g","주간 목표",NOW,2,0));store.adjustWeeklyGoal("g",1);
        store.saveTags(List.of(),List.of(new Tag("eventtag","일정 태그")));store.deleteEvent("e");store.deleteTask("daily");
        check(store.load().monthlyTasks().equals(List.of(month)),"unrelated writes keep monthly TODOs intact");
        store.toggleMonthlyTask("month");check(store.load().weeklyTasks().get(0).completed(),"monthly edits preserve weekly completion");
        store.saveTodoTags(List.of(tag),List.of());State cleaned=new PlannerStore(store.file()).load();
        check(cleaned.monthlyTasks().get(0).completed()&&cleaned.monthlyTasks().get(0).tagIds().isEmpty(),"shared tag deletion clears monthly references without deleting task");
        check(cleaned.weeklyTasks().get(0).tagIds().isEmpty(),"shared tag deletion clears weekly references atomically");
        JsonObject old=JsonParser.parseString(Files.readString(store.file())).getAsJsonObject();old.getAsJsonObject("state").remove("monthlyTasks");Files.writeString(store.file(),old.toString());String before=Files.readString(store.file());
        check(store.load().monthlyTasks().isEmpty()&&Files.readString(store.file()).equals(before),"legacy data reads without migration writes");
        store.saveMonthlyTask(month.withTags(List.of()));check(store.load().goals().get(0).completed()==2,"legacy goal remains after first monthly save");
        store.deleteMonthlyTask("month");check(store.load().monthlyTasks().isEmpty()&&store.load().weeklyTasks().size()==1,"delete only affects selected monthly TODO");
    }
    static Event event(String id,String title,LocalDate day,int hour,EventColor color,boolean important){return new Event(id,title,"",day.atTime(hour,0),day.atTime(hour+2,0),false,color,List.of(),important,Repeat.NONE,-1);}
    static void fixtures(PlannerStore store)throws Exception{
        store.saveTodoTags(List.of(),List.of(new Tag("finance","금융"),new Tag("math","미적")));
        store.saveEvent(new Event("program","프입","",NOW.atTime(9,0),NOW.atTime(12,0),false,EventColor.ORANGE,List.of(),false,Repeat.WEEKLY,-1));
        store.saveEvent(new Event("finance","금융의 이해","",NOW.atTime(15,0),NOW.atTime(18,0),false,EventColor.YELLOW,List.of(),false,Repeat.WEEKLY,-1));
        for(int day:new int[]{3,10,17,24}){store.saveEvent(event("creative"+day,"창사 수업",NOW.withDayOfMonth(day),11,EventColor.PINK,false));store.saveEvent(event("spanish"+day,"스페인어 수업",NOW.withDayOfMonth(day),16,EventColor.BLUE,false));}
        for(int day:new int[]{5,12,19,26}){store.saveEvent(event("history"+day,"오한사",NOW.withDayOfMonth(day),12,EventColor.TEAL,false));store.saveEvent(event("art"+day,"현예이",NOW.withDayOfMonth(day),15,EventColor.TEAL,false));}
        for(int day:new int[]{6,13,20,27})store.saveEvent(event("support"+day,"학지",NOW.withDayOfMonth(day),14,EventColor.GREEN,false));
        store.saveEvent(new Event("mt","다락방 MT","",NOW.withDayOfMonth(7).atStartOfDay(),NOW.withDayOfMonth(9).atStartOfDay(),true,EventColor.BLUE,List.of(),true,Repeat.NONE,-1));
        store.saveEvent(new Event("prep","프로젝트 중간 발표 준비","",NOW.withDayOfMonth(17).atStartOfDay(),NOW.withDayOfMonth(20).atStartOfDay(),true,EventColor.YELLOW,List.of(),false,Repeat.NONE,-1));
        store.saveEvent(event("report","금융의 이해 리포트",NOW.withDayOfMonth(11),21,EventColor.YELLOW,true));store.saveEvent(event("submit","발표 자료 제출",NOW.withDayOfMonth(20),20,EventColor.YELLOW,true));store.saveEvent(event("presentation","프로젝트 중간 발표",NOW.withDayOfMonth(25),14,EventColor.YELLOW,true));
        store.saveTask(new Task("daily1","프입 수업 복습하고 실습 정리하기",NOW,"",false));store.saveTask(new Task("daily2","금융의 이해 3장 요약하기",NOW,"",false));
        for(int i=0;i<5;i++)store.saveMonthlyTask(new MonthlyTask("month"+i,new String[]{"금융의 이해 리포트 제출","프로젝트 발표 자료 정리","11월 학습 회고 작성","수강 자료 폴더 정리","11월 학습 계획 세우기"}[i],i<3?NOW.withDayOfMonth(new int[]{11,20,30}[i]):null,NOW,List.of(i<3?"finance":"math"),i>=3));
        store.saveMonthlyTask(new MonthlyTask("dec","다음 달 할 일",NOW,NOW.plusMonths(1),List.of(),false));
    }
    static void ui(PlannerStore store)throws Exception{
        PlannerDesign p=new PlannerDesign(store,CLOCK);try{
            p.setMonthly(true);p.setSize(1550,1016);layout(p);PlannerMonthView v=p.monthlyView;
            check(p.calendar.getParent()==v&&v.daily.getX()==28,"monthly owns shared calendar and uses Figma content inset");
            check(p.calendar.getBounds().equals(new Rectangle(28,112,1178,692)),"reference calendar geometry");
            check(v.daily.getBounds().equals(new Rectangle(28,820,450,168))&&v.quick.getBounds().equals(new Rectangle(494,820,712,168)),"reference lower workspace geometry");
            check(v.selected.getBounds().equals(new Rectangle(1226,112,296,246))&&v.todos.getHeight()==310&&v.upcoming.getHeight()==288,"reference side column geometry");
            check(v.monthTasks().size()==5&&p.taskRows.getComponentCount()==2,"monthly period filters independently of deadline and daily tasks");check(v.upcomingEvents().size()==4,"D-day includes only important occurrences");for(JScrollPane pane:List.of(v.dailyScroll,v.selectedScroll,v.todoScroll,v.filterScroll,v.upcomingScroll))check(pane instanceof FadeScrollPane,"every monthly list uses shared overflow hints");
            PlannerCalendar.Month grid=(PlannerCalendar.Month)((PlannerCalendar)p.calendar.getComponent(0)).getComponent(0);
            check(grid.rows==6&&grid.first.equals(LocalDate.of(2026,10,26)),"November is Monday-first and includes adjacent months");
            var mt=grid.spans.entrySet().stream().filter(e->e.getValue().occurrence().event().id().equals("mt")).toList();check(mt.size()==1&&mt.get(0).getValue().firstDay()==5&&mt.get(0).getValue().lastDay()==6,"exclusive multi-day event spans Saturday and Sunday only");
            render(p,Path.of("build/monthly-planner-design/implemented-main.png"));
            Component daily=p.taskRows.getComponent(0),upcoming=p.upcomingRows.getComponent(0),calendar=p.calendar.getComponent(0);p.refresh();check(p.taskRows.getComponent(0)==daily&&p.upcomingRows.getComponent(0)==upcoming&&p.calendar.getComponent(0)==calendar,"unchanged refresh preserves components and scrolling");
            ((PlannerMonthView.TodoRow)daily).check.doClick();check(store.load().tasks().get(0).completed(),"daily checkbox persists through existing store");
            PlannerMonthView.TodoRow row=(PlannerMonthView.TodoRow)v.todoRows.getComponent(0);row.check.doClick();check(store.load().monthlyTasks().get(0).completed(),"monthly checkbox persists separately");
            v.tagFilter="math";v.renderTodos();check(v.todoRows.getComponentCount()==2,"monthly filter follows shared tag IDs");v.tagFilter="";v.renderTodos();
            v.selectDate(NOW.withDayOfMonth(11));check(p.taskDate.getDayOfMonth()==11&&v.selectedDateLabel.getText().startsWith("11월 11일"),"date selection updates both agenda and daily TODO");check(p.calendar.getComponent(0)==calendar,"date selection within a month preserves calendar components");
            PlannerWeekEditors.Todo form=PlannerWeekEditors.Todo.monthly(p,null);form.title.setText("새 월간 TODO");form.week.setDate(LocalDate.of(2027,3,1));form.deadline.setDate(LocalDate.of(2027,3,31));form.week.setDate(LocalDate.of(2027,2,1));check(form.deadline.date().equals(LocalDate.of(2027,2,28)),"changing month clamps deadline to its last date");check(!form.deadline.selectable(LocalDate.of(2027,3,1)),"deadline picker rejects another month");form.noDeadline.setSelected(true);form.save();check(store.load().monthlyTasks().stream().anyMatch(t->t.title().equals("새 월간 TODO")&&t.month().equals(LocalDate.of(2027,2,1))&&t.deadline()==null),"monthly editor creates its own period without a deadline");
            p.goToday();p.navigate(1);check(p.anchor.getMonthValue()==12&&v.monthTasks().size()==1,"month navigation switches monthly TODO collection");p.goToday();check(p.anchor.equals(NOW)&&v.selectedDate.equals(NOW),"Today restores real date and selected agenda");
            p.setMonthly(false);check(p.calendar.getParent()==p.weeklyView&&p.weeklyView.isVisible()&&!v.isVisible(),"week switch restores weekly view");p.setMonthly(true);check(p.calendar.getParent()==v,"month switch restores monthly view");
            for(int width:new int[]{1550,1120,900,680,400}){p.setSize(width,v.minimumHeight(width));layout(p);for(Component c:List.of(p.calendar,v.daily,v.quick,v.selected,v.todos,v.upcoming)){check(c.getWidth()>0&&c.getHeight()>0&&c.getX()>=0&&c.getY()>=0&&c.getX()+c.getWidth()<=width&&c.getY()+c.getHeight()<=p.getHeight(),"card remains reachable at width "+width+": "+c.getBounds());}if(width==900||width==680)render(p,Path.of("build/monthly-planner-design/implemented-"+width+".png"));}
            int[] sizes={16,20,15,15,12,12,16,12,12,14,16,10};String[] icons={"add","bell","left","right","daily-left","daily-right","plus","list-selected","list","arrow","more","completed-check"};for(int i=0;i<icons.length;i++){var in=PlannerMonthlyTest.class.getResourceAsStream("/dev/synesis/poc/planner/monthly/"+icons[i]+".png");check(in!=null,"asset is packaged: "+icons[i]);BufferedImage image=ImageIO.read(in);check(image.getWidth()==sizes[i]*3&&image.getHeight()==sizes[i]*3,"asset retains original aspect at 3x: "+icons[i]);boolean visible=false;for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++)if((image.getRGB(x,y)>>>24)>0)visible=true;check(visible,"asset is nonempty: "+icons[i]);}
        }finally{p.dispose();}
    }
    static void scrollHints()throws Exception{
        JPanel content=new JPanel(){@Override protected void paintComponent(Graphics graphics){graphics.setColor(PlannerStyle.NAVY);graphics.fillRect(0,0,getWidth(),getHeight());}};
        content.setPreferredSize(new Dimension(160,400));FadeScrollPane pane=(FadeScrollPane)PlannerMonthView.quiet(content);pane.setSize(180,120);layout(pane);
        Rectangle r=pane.getViewport().getBounds();int x=r.x+r.width/2,top=r.y+1,bottom=r.y+r.height-2;
        BufferedImage first=paint(pane);check(first.getRGB(x,top)==PlannerStyle.NAVY.getRGB(),"no top hint at start");check(first.getRGB(x,bottom)!=PlannerStyle.NAVY.getRGB(),"bottom hint for clipped items");
        pane.getViewport().setViewPosition(new Point(0,100));BufferedImage middle=paint(pane);check(middle.getRGB(x,top)!=PlannerStyle.NAVY.getRGB()&&middle.getRGB(x,bottom)!=PlannerStyle.NAVY.getRGB(),"both hints while scrolled between ends");
        pane.getViewport().setViewPosition(new Point(0,pane.getViewport().getViewSize().height-r.height));BufferedImage last=paint(pane);check(last.getRGB(x,bottom)==PlannerStyle.NAVY.getRGB()&&last.getRGB(x,top)!=PlannerStyle.NAVY.getRGB(),"bottom hint disappears at end");
        content.setPreferredSize(new Dimension(160,40));pane.getViewport().setViewSize(new Dimension(160,40));pane.getViewport().setViewPosition(new Point());layout(pane);BufferedImage fits=paint(pane);check(fits.getRGB(x,top)==PlannerStyle.NAVY.getRGB()&&fits.getRGB(x,bottom)==PlannerStyle.NAVY.getRGB(),"no hints when all content fits");
    }
    static BufferedImage paint(JComponent c){BufferedImage image=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();c.printAll(g);g.dispose();return image;}
    static void layout(Container c){for(int i=0;i<3;i++)layoutOnce(c);}
    static void layoutOnce(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container n)layoutOnce(n);}
    static void render(JComponent c,Path file)throws Exception{Files.createDirectories(file.getParent());BufferedImage image=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();c.printAll(g);g.dispose();ImageIO.write(image,"png",file.toFile());}
}
