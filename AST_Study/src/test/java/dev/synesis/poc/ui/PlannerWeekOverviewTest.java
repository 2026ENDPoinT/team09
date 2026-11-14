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

/** Weekly geometry, the new all-day band, and removal of legacy task badges. */
public final class PlannerWeekOverviewTest {
    static int checks;
    static final Path OUT=Path.of("tmp/calendar-figma-20261019");
    static final LocalDate MONDAY=LocalDate.of(2026,10,12);
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        PlannerStore store=new PlannerStore(Files.createTempDirectory("planner-figma-calendar-").resolve("planner.json"));
        String[][] fixture={
            {"0","영어 수업","09:00","10:30","BLUE"},{"0","점심 식사","12:00","13:00","OCHRE"},
            {"0","C++ 과제","14:00","16:00","ROSE"},{"0","헬스","19:00","20:30","TEAL"},
            {"1","스페인어","10:00","11:30","ROSE"},{"1","도서관","13:00","16:00","BLUE"},{"1","저녁 약속","18:00","20:00","SLATE"},
            {"2","전시 관람","08:00","11:00","TEAL"},{"2","프로젝트 개발","13:00","17:00","ROSE"},{"2","스페인어 복습","20:00","22:00","BLUE"},
            {"3","한국사","09:00","10:30","SLATE"},{"3","점심 식사","12:30","13:30","OCHRE"},{"3","팀 프로젝트 회의","14:00","16:00","TEAL"},{"3","친구 모임","19:00","22:00","OCHRE"},
            {"4","현대예술의 이해","10:00","11:30","ROSE"},{"4","금융의 이해","15:00","17:00","BLUE"},
            {"5","카페 공부","11:00","14:00","TEAL"},{"5","개발 스프린트","16:00","20:00","SLATE"},
            {"6","주간 정리","10:00","12:00","BLUE"},{"6","자유 시간","15:00","18:00","OCHRE"}
        };
        for(int i=0;i<fixture.length;i++){String[] row=fixture[i];LocalDate date=MONDAY.plusDays(Integer.parseInt(row[0]));store.saveEvent(new Event("figma-"+i,row[1],"",date.atTime(LocalTime.parse(row[2])),date.atTime(LocalTime.parse(row[3])),false,EventColor.valueOf(row[4]),List.of(),false,Repeat.NONE,-1));}
        Files.createDirectories(OUT);
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign planner=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-14T03:00:00Z"),ZoneId.of("Asia/Seoul")));
            planner.setSize(1430,844);layout(planner);
            PlannerCalendar calendar=(PlannerCalendar)planner.calendar.getComponent(0);PlannerCalendar.Week week=(PlannerCalendar.Week)calendar.getComponent(0);
            PlannerCalendar.WeekHeader header=(PlannerCalendar.WeekHeader)week.timeline.getColumnHeader().getView();
            check(header.getComponentCount()==7&&header.getHeight()==48,"only seven date headings in fixed 48px header");
            check(week.body.minuteY(60)-week.body.minuteY(0)==28,"Figma one-hour interval is exactly 28px");
            check(PlannerCalendar.dayX(1066,0)==44&&PlannerCalendar.dayX(1066,7)==1066,"44px gutter and seven equal days");
            check(week.body.positions.size()==20,"all Figma fixture events rendered");
            for(var entry:week.body.positions.entrySet()){
                var position=entry.getValue();JButton button=entry.getKey();int span=week.body.minuteY(position.end())-week.body.minuteY(position.start());
                check(button.getHeight()==span-4,"2px vertical inset on each event edge");
                check(button.getBorder()==null,"no inherited native border on event block");
                check(button.getX()==PlannerCalendar.dayX(week.body.getWidth(),position.day())+6,"6px event column inset");
            }
            BufferedImage calendarBefore=paint(calendar);save(calendarBefore,"calendar-figma.png");save(paint(planner),"weekly-screen.png");
            for(int i=0;i<3;i++)store.saveEvent(new Event("all-day-"+i,"종일 공부 "+i,"",MONDAY.plusDays(6).atStartOfDay(),MONDAY.plusDays(7).atStartOfDay(),true,EventColor.ROSE,List.of(),false,Repeat.NONE,-1));
            planner.accept(store.load());layout(planner);calendar=(PlannerCalendar)planner.calendar.getComponent(0);
            BufferedImage withAllDay=paint(calendar);
            check(!Arrays.equals(pixels(calendarBefore),pixels(withAllDay)),"all-day records now add the requested header band");
            for(int i=0;i<24;i++)store.saveTask(new Task("task-"+i,"옛 헤더 할 일 "+i,MONDAY.plusDays(6),"",i%2==0));
            planner.accept(store.load());layout(planner);calendar=(PlannerCalendar)planner.calendar.getComponent(0);week=(PlannerCalendar.Week)calendar.getComponent(0);header=(PlannerCalendar.WeekHeader)week.timeline.getColumnHeader().getView();
            check(header.getComponentCount()==7&&week.spans.rows==3&&header.getHeight()==48,"seven fixed date headings with floating all-day rows; no task badges");
            check(Arrays.equals(pixels(withAllDay),pixels(paint(calendar))),"legacy tasks cannot change calendar or all-day band pixels");
            check(find(calendar,PlannerTaskSummary.class)==null,"no task-hover popup trigger remains in calendar");
            check(store.load().tasks().size()==24&&store.load().events().size()==23,"removing legacy UI preserves user data");
            JPanel agenda=planner.dayEventsPanel(MONDAY.plusDays(6));check(buttonText(agenda,"종일 · 종일 공부 0"),"all-day schedule still accessible through the date's event list");
            save(paint(calendar),"calendar-with-legacy-data.png");
            JViewport viewport=week.timeline.getViewport();viewport.setViewPosition(new Point(0,0));save(paint(calendar),"calendar-midnight.png");
            check(viewport.getViewPosition().y==0,"00:00 reachable by scroll");viewport.setViewPosition(new Point(0,week.body.getHeight()-viewport.getHeight()));save(paint(calendar),"calendar-day-end.png");
            check(viewport.getViewPosition().y+viewport.getHeight()==week.body.getHeight(),"24:00 boundary reachable");
            week.timeline.getVerticalScrollBar().setValue(168);planner.refresh();layout(planner);week=(PlannerCalendar.Week)((PlannerCalendar)planner.calendar.getComponent(0)).getComponent(0);
            check(Math.abs(week.timeline.getViewport().getViewPosition().y-168)<=1,"refresh preserves 06:00 scroll position");
            store.saveEvent(new Event("overlap","겹치는 일정","",MONDAY.atTime(9,30),MONDAY.atTime(11,0),false,EventColor.TEAL,List.of(),true,Repeat.NONE,-1));planner.accept(store.load());layout(planner);
            week=(PlannerCalendar.Week)((PlannerCalendar)planner.calendar.getComponent(0)).getComponent(0);List<JButton> overlap=week.body.positions.entrySet().stream().filter(e->e.getValue().day()==0&&e.getValue().start()<660).map(Map.Entry::getKey).toList();
            check(overlap.size()==2&&!overlap.get(0).getBounds().intersects(overlap.get(1).getBounds()),"overlapping events remain distinct click targets");
            for(int width:new int[]{1066,876,640}){
                calendar=(PlannerCalendar)planner.calendar.getComponent(0);calendar.setSize(width,496);layout(calendar);week=(PlannerCalendar.Week)calendar.getComponent(0);
                check(week.body.getWidth()==week.timeline.getColumnHeader().getView().getWidth(),"headers and body align at width "+width);
                check(week.body.timeAt(new Point(week.body.getWidth()-4,week.body.minuteY(1439))).getDayOfWeek()==DayOfWeek.SUNDAY,"Sunday click mapping at "+width);
            }
        }catch(Exception ex){throw new RuntimeException(ex);}});
        System.out.println("PASS: "+checks+" Figma calendar layout, legacy-UI removal and interaction checks");
    }
    static boolean buttonText(Container c,String text){for(Component child:c.getComponents()){if(child instanceof JButton b&&b.getText().equals(text))return true;if(child instanceof Container nested&&buttonText(nested,text))return true;}return false;}
    static <T> T find(Container c,Class<T> type){for(Component child:c.getComponents()){if(type.isInstance(child))return type.cast(child);if(child instanceof Container nested){T result=find(nested,type);if(result!=null)return result;}}return null;}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static BufferedImage paint(JComponent c){BufferedImage image=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();c.printAll(g);g.dispose();return image;}
    static int[] pixels(BufferedImage image){return image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth());}
    static void save(BufferedImage image,String name)throws Exception{ImageIO.write(image,"png",OUT.resolve(name).toFile());}
}
