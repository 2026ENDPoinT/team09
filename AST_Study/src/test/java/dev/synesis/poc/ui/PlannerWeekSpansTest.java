package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Real calendar layout, independent scrolling, date boundaries and existing edit action. */
public final class PlannerWeekSpansTest {
    static int checks;
    static final LocalDate MONDAY=LocalDate.of(2026,10,19);
    static final Path OUT=Path.of("tmp/planner-week-spans-20261019");
    static void check(boolean result,String message){checks++;if(!result)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);
        Path data=Files.createTempDirectory("planner-week-spans-").resolve("planner.json");
        PlannerStore store=new PlannerStore(data);
        SwingUtilities.invokeAndWait(()->{try {
            PlannerDesign planner=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-19T03:00:00Z"),ZoneId.of("Asia/Seoul")));
            JRootPane root=new JRootPane();root.setContentPane(planner);root.setSize(1430,900);layout(root);
            check(header(planner).getHeight()==48&&week(planner).spans.rows==0,"empty band takes no space");
            Rectangle originalHours=new Rectangle(week(planner).timeline.getViewport().getBounds());
            store.saveEvent(event("exam","중간고사 기간",MONDAY.minusDays(1).atStartOfDay(),MONDAY.plusDays(13).atStartOfDay(),true));
            store.saveEvent(event("study","진짜 공부하기..",MONDAY.plusDays(3).atStartOfDay(),MONDAY.plusDays(4).atStartOfDay(),true));
            store.saveEvent(event("timed","현예시험",MONDAY.plusDays(3).atTime(15,0),MONDAY.plusDays(3).atTime(17,0),false));
            planner.accept(store.load());layout(root);
            PlannerWeekSpans band=week(planner).spans;
            check(band.rows==2&&!band.getVerticalScrollBar().isVisible(),"two overlapping spans are fully visible");
            check(week(planner).timeline.getViewport().getBounds().equals(originalHours),"floating bars never move or shrink the hourly viewport");
            check(!band.isOpaque()&&!band.getViewport().isOpaque()&&!band.body.isOpaque(),"hourly lines remain visible through overlay gaps");
            Point gap=new Point(PlannerCalendar.dayX(band.getWidth(),0)+12,52);
            check(!band.contains(gap.x,gap.y),"empty overlay area passes clicks and wheel through to hourly grid");
            Point gapInTimeline=SwingUtilities.convertPoint(band,gap,week(planner).timeline);
            check(SwingUtilities.getDeepestComponentAt(week(planner).timeline,gapInTimeline.x,gapInTimeline.y)==week(planner).body,"empty overlay gap targets underlying click-to-add grid");
            Point barPoint=SwingUtilities.convertPoint(band.body,new Point(button(band,"study").getX()+10,button(band,"study").getY()+10),week(planner).timeline);
            check(SwingUtilities.getDeepestComponentAt(week(planner).timeline,barPoint.x,barPoint.y)==button(band,"study"),"floating bar retains its own edit click target");
            var exam=span(band,"exam");check(exam.firstDay()==0&&exam.lastDay()==6,"long event clipped to current week");
            check(button(band,"exam").getText().contains("10/18 – 10/31"),"title retains original inclusive date range");
            check(week(planner).body.positions.size()==1,"normal timed event stays in hourly calendar");
            save(planner,"weekly-two-rows.png");save((JComponent)planner.calendar.getComponent(0),"calendar-two-rows.png");
            store.saveEvent(event("midnight","자정 종료",MONDAY.atTime(22,0),MONDAY.plusDays(1).atStartOfDay(),false));
            store.saveEvent(event("overnight","밤샘 개발",MONDAY.plusDays(1).atTime(22,0),MONDAY.plusDays(3).atStartOfDay(),false));
            store.saveEvent(event("hackathon","해커톤",MONDAY.plusDays(4).atTime(18,0),MONDAY.plusDays(5).atTime(14,30),false));
            store.saveEvent(event("daily","매일 종일",MONDAY.atStartOfDay(),MONDAY.plusDays(1).atStartOfDay(),true,Repeat.DAILY));
            planner.accept(store.load());layout(root);band=week(planner).spans;
            check(band.rows==3,"non-overlapping dates share rows");
            check(band.spans.values().stream().filter(s->s.occurrence().event().id().equals("daily")).count()==7,"daily recurrence retains seven distinct bars");
            check(span(band,"overnight").firstDay()==1&&span(band,"overnight").lastDay()==2,"multi-date timed event excludes midnight end date");
            var positions=week(planner).body.positions.values();
            check(positions.size()==6&&!band.spans.values().stream().anyMatch(s->s.occurrence().event().id().equals("midnight")),"midnight exclusive end remains a single-date hourly event");
            check(positions.stream().anyMatch(p->p.day()==1&&p.start()==1320&&p.end()==1440),"overnight begins at the actual start time");
            check(positions.stream().anyMatch(p->p.day()==2&&p.start()==0&&p.end()==1440),"overnight occupies the full intervening day without an extra midnight block");
            check(span(band,"hackathon").lastDay()==5&&positions.stream().anyMatch(p->p.day()==5&&p.start()==0&&p.end()==870),"two-day event keeps its banner and ends at the actual time");
            for(int i=0;i<6;i++)store.saveEvent(event("extra-"+i,"겹치는 종일 일정 "+(i+1),MONDAY.atStartOfDay(),MONDAY.plusDays(7).atStartOfDay(),true));
            planner.accept(store.load());layout(root);band=week(planner).spans;
            byte[] before=Files.readAllBytes(data);
            check(band.rows==9&&band.getViewport().getHeight()==128,"exactly four rows visible, with no fifth-row peek");
            check(band.getVerticalScrollBar().isVisible()&&!band.getHorizontalScrollBar().isVisible(),"overflow uses only independent vertical scrollbar");
            check(header(planner).getHeight()==48&&band.getY()==week(planner).timeline.getViewport().getY(),"overlay starts on hourly grid without expanding date header");
            for(int width:new int[]{1066,876,640}){
                JComponent calendar=(JComponent)planner.calendar.getComponent(0);calendar.setSize(width,550);layout(calendar);
                check(band.body.getWidth()==week(planner).body.getWidth(),"all-day and hourly columns align at "+width);
                for(var entry:band.spans.entrySet()){
                    var s=entry.getValue();Rectangle b=entry.getKey().getBounds();
                    check(b.x==PlannerCalendar.dayX(band.body.getWidth(),s.firstDay())+4&&b.x+b.width==PlannerCalendar.dayX(band.body.getWidth(),s.lastDay()+1)-4,"span follows exact day columns at "+width);
                }
            }
            layout(root);int hourY=week(planner).timeline.getViewport().getViewPosition().y;
            wheel(band);check(band.getViewport().getViewPosition().y>0&&week(planner).timeline.getViewport().getViewPosition().y==hourY,"wheel over band only scrolls all-day rows");
            int bandY=band.getViewport().getViewPosition().y;
            week(planner).timeline.getVerticalScrollBar().setValue(0);
            check(band.getViewport().getViewPosition().y==bandY&&header(planner).getY()==0,"hourly scroll leaves all-day band and headings fixed");
            band.getVerticalScrollBar().setValue(band.body.getHeight());
            check(band.getViewport().getViewPosition().y+band.getViewport().getHeight()==band.body.getHeight(),"last all-day row is reachable");
            save((JComponent)planner.calendar.getComponent(0),"calendar-scrolled-last-rows.png");
            int savedY=band.getViewport().getViewPosition().y;planner.refresh();layout(root);band=week(planner).spans;
            check(band.getViewport().getViewPosition().y==savedY,"refresh preserves all-day scroll position");
            planner.anchor=MONDAY.plusDays(2);planner.refresh();layout(root);
            check(week(planner).spans.getViewport().getViewPosition().y==savedY,"same-week date change preserves all-day scroll");
            planner.anchor=MONDAY.plusWeeks(1);planner.refresh();layout(root);
            check(week(planner).spans.getViewport().getViewPosition().y==0,"new week starts at first all-day row");
            planner.anchor=MONDAY;planner.refresh();layout(root);band=week(planner).spans;
            check(band.getViewport().getViewPosition().y==0,"returning week starts at first row");
            save((JComponent)planner.calendar.getComponent(0),"calendar-four-row-cap.png");
            button(band,"exam").doClick(0);
            PlannerDayOverlay overlay=PlannerWeekOverviewTest.find(root.getLayeredPane(),PlannerDayOverlay.class);
            check(overlay!=null,"bar click opens existing in-window editor");overlay.animation.stop();
            PlannerDialogs.EventEditor editor=PlannerWeekOverviewTest.find(overlay,PlannerDialogs.EventEditor.class);
            check(editor!=null&&editor.original.id().equals("exam")&&editor.allDay.isSelected(),"existing all-day event is loaded for editing");
            PlannerDialogs.requestClose(editor);
            check(overlay.getParent()==null&&Arrays.equals(before,Files.readAllBytes(data)),"scrolling and cancelled editing never mutate stored events");
            check(week(planner).body.minuteY(60)-week(planner).body.minuteY(0)==PlannerWeekCalendarSkin.HOUR_HEIGHT,"hourly grid retains one-hour cell geometry");
            check(week(planner).body.gridTop()==band.visibleHeight(),"hourly timeline gains exactly the floating overlay height in extra scroll space");
            var hours=week(planner).timeline.getViewport();hours.setViewPosition(new Point(0,0));
            check(week(planner).body.minuteY(0)-hours.getViewPosition().y>=band.getHeight(),"00:00 can scroll fully below all-day bars");
            check(week(planner).body.timeAt(new Point(100,week(planner).body.gridTop()-1))==null,"extra pre-midnight scroll space cannot create an accidental event");
            planner.refresh();layout(root);
            check(week(planner).timeline.getViewport().getViewPosition().y==0,"extra top scroll position survives refresh");
            sparseOverflow(root);
        }catch(Exception ex){throw new RuntimeException(ex);}});
        System.out.println("PASS: "+checks+" weekly all-day/continuous span checks");
    }
    static Event event(String id,String title,LocalDateTime start,LocalDateTime end,boolean allDay){return event(id,title,start,end,allDay,Repeat.NONE);}
    static Event event(String id,String title,LocalDateTime start,LocalDateTime end,boolean allDay,Repeat repeat){return new Event(id,title,"",start,end,allDay,EventColor.TEAL,List.of(),false,repeat,-1);}
    static PlannerCalendar.Week week(PlannerDesign planner){return (PlannerCalendar.Week)((PlannerCalendar)planner.calendar.getComponent(0)).getComponent(0);}
    static PlannerCalendar.WeekHeader header(PlannerDesign planner){return (PlannerCalendar.WeekHeader)week(planner).timeline.getColumnHeader().getView();}
    static JButton button(PlannerWeekSpans band,String id){return band.spans.keySet().stream().filter(b->band.spans.get(b).occurrence().event().id().equals(id)).findFirst().orElseThrow();}
    static PlannerWeekSpans.Span span(PlannerWeekSpans band,String id){return band.spans.get(button(band,id));}
    static void wheel(JComponent c){c.dispatchEvent(new MouseWheelEvent(c,MouseWheelEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,100,50,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,1,1));}
    static void layout(Container c){PlannerWeekOverviewTest.layout(c);}
    static void save(JComponent c,String filename)throws Exception{BufferedImage image=PlannerWeekOverviewTest.paint(c);ImageIO.write(image,"png",OUT.resolve(filename).toFile());}
    static void sparseOverflow(JRootPane root)throws Exception{
        PlannerStore store=new PlannerStore(Files.createTempDirectory("planner-sunday-overflow-").resolve("planner.json"));
        for(int i=0;i<6;i++)store.saveEvent(event("sunday-"+i,"일요일 종일 "+i,MONDAY.plusDays(6).atStartOfDay(),MONDAY.plusDays(7).atStartOfDay(),true));
        store.saveEvent(event("early","00시부터 04시까지",MONDAY.plusDays(6).atStartOfDay(),MONDAY.plusDays(6).atTime(4,0),false));
        PlannerDesign p=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-19T03:00:00Z"),ZoneId.of("Asia/Seoul")));root.setContentPane(p);layout(root);
        var w=week(p);var band=w.spans;var view=band.getViewport();int sunday=PlannerCalendar.dayX(band.body.getWidth(),6)+30;
        for(int y:new int[]{0,32}){
            view.setViewPosition(new Point(0,y));
            BufferedImage layer=new BufferedImage(view.getWidth(),view.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=layer.createGraphics();view.printAll(g);g.dispose();
            check((layer.getRGB(80,view.getHeight()-2)>>>24)==0,"bottom overflow fade never paints empty Monday at scroll "+y);
            check((layer.getRGB(sunday,view.getHeight()-2)>>>24)>0,"bottom overflow fade stays on occupied Sunday at scroll "+y);
            if(y>0)check((layer.getRGB(80,1)>>>24)==0&&(layer.getRGB(sunday,1)>>>24)>0,"top overflow fade also stays on occupied Sunday");
        }
        view.setViewPosition(new Point(0,0));w.timeline.getViewport().setViewPosition(new Point(0,0));
        JButton early=w.body.positions.entrySet().stream().filter(e->e.getValue().day()==6).findFirst().orElseThrow().getKey();
        check(early.getY()>=band.getHeight()&&early.getY()+early.getHeight()<=w.timeline.getViewport().getHeight(),"entire Sunday 00–04 event is visible below fixed all-day overlay");
        save((JComponent)p.calendar.getComponent(0),"sunday-overflow-midnight-visible.png");
        w.timeline.getViewport().setViewPosition(new Point(0,w.body.minuteY(240)));
        JButton above=w.edgeBadges.stream().filter(b->b.isVisible()&&Boolean.TRUE.equals(b.getClientProperty("planner.edgeAbove"))).findFirst().orElseThrow();
        check(above.getY()>=band.getY()+band.coveredHeight(6),"hidden-event bubble avoids floating all-day bars");above.doClick(0);
        check(early.getY()-w.timeline.getViewport().getViewPosition().y>=band.coveredHeight(6),"hidden-event reveal scrolls early event below overlay");
        int y=w.timeline.getViewport().getViewPosition().y;wheel(band);
        check(w.timeline.getViewport().getViewPosition().y==y,"independent all-day scrolling preserves newly reachable early-hour position");
    }
}
