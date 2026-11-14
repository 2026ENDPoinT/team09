package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;

public final class PlannerMonthSpanTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static void event(PlannerStore store,String id,String title,LocalDateTime start,LocalDateTime end,boolean allDay,EventColor color)throws Exception{store.saveEvent(new PlannerModel.Event(id,title,"",start,end,allDay,color,List.of(),true,Repeat.NONE,-1));}
    public static void main(String[] args)throws Exception{
        PlannerStore store=new PlannerStore(Files.createTempDirectory("planner-month-span-").resolve("planner.json"));
        event(store,"span","연속 일정",LocalDate.of(2026,10,14).atStartOfDay(),LocalDate.of(2026,10,17).atStartOfDay(),true,EventColor.TEAL);
        event(store,"cross","주말부터 다음 주까지",LocalDate.of(2026,10,17).atStartOfDay(),LocalDate.of(2026,10,20).atStartOfDay(),true,EventColor.OCHRE);
        event(store,"midnight","밤에 시작하는 일정",LocalDate.of(2026,10,22).atTime(22,0),LocalDate.of(2026,10,24).atStartOfDay(),false,EventColor.ROSE);
        event(store,"month","지난달부터 이어지는 일정",LocalDate.of(2026,9,25).atStartOfDay(),LocalDate.of(2026,10,2).atStartOfDay(),true,EventColor.NAVY);
        for(int i=0;i<7;i++)event(store,"crowd"+i,"겹치는 일정 "+i,LocalDate.of(2026,10,15).atTime(9+i,0),LocalDate.of(2026,10,15).atTime(10+i,0),false,EventColor.BLUE);
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign planner=new PlannerDesign(store,Clock.fixed(Instant.parse("2026-10-18T03:00:00Z"),ZoneId.of("Asia/Seoul")));planner.setMonthly(true);PlannerCalendar cal=(PlannerCalendar)planner.calendar.getComponent(0);PlannerCalendar.Month month=(PlannerCalendar.Month)cal.getComponent(0);
            month.setSize(980,800);layout(month);Path out=Path.of("build/planner-month-span-20261018");Files.createDirectories(out);render(month,out.resolve("wide.png"));
            var span=month.spans.entrySet().stream().filter(e->e.getValue().occurrence().event().id().equals("span")).toList();
            check(span.size()==1,"a three-day event creates one weekly bar, not three separate daily buttons");var s=span.get(0);check(s.getValue().firstDay()==2&&s.getValue().lastDay()==4&&s.getKey().getWidth()==412,"continuous bar spans Wednesday through Friday at full column width");check(s.getKey().isVisible(),"long event remains visible ahead of crowded single-day items");
            var cross=month.spans.values().stream().filter(v->v.occurrence().event().id().equals("cross")).toList();check(cross.size()==2&&cross.get(0).firstDay()==5&&cross.get(0).lastDay()==6&&cross.get(1).firstDay()==0&&cross.get(1).lastDay()==0,"week boundary splits into Saturday-Sunday and Monday continuations");
            var midnight=month.spans.values().stream().filter(v->v.occurrence().event().id().equals("midnight")).findFirst().orElseThrow();check(midnight.firstDay()==3&&midnight.lastDay()==4,"midnight end excludes the following Saturday");
            var clipped=month.spans.values().stream().filter(v->v.occurrence().event().id().equals("month")).findFirst().orElseThrow();check(clipped.firstDay()==0&&clipped.lastDay()==3,"event beginning before the visible grid clips to the first Monday");
            for(int[] size:new int[][]{{980,800},{630,320},{328,200},{980,800}}){month.setSize(size[0],size[1]);layout(month);verify(month);render(month,out.resolve("month-"+size[0]+"x"+size[1]+".png"));}
            check(month.spans.get(s.getKey())==s.getValue()&&s.getKey().isVisible(),"resizing restores the same continuous event bar without changing data");
            check(store.load().events().size()==11,"layout and overflow calculation preserve stored events");
        }catch(Exception ex){throw new RuntimeException(ex);}});
        System.out.println("PASS: "+checks+" monthly span, midnight, week-boundary and overflow checks");
    }
    static void verify(PlannerCalendar.Month month){
        for(int i=0;i<month.rows*7;i++){
            int day=i;long visible=month.spans.entrySet().stream().filter(e->e.getKey().isVisible()&&e.getValue().row()==day/7&&e.getValue().firstDay()<=day%7&&e.getValue().lastDay()>=day%7).count();int hidden=month.items.get(i).size()-(int)visible;
            check(month.hiddenCounts.getOrDefault(i,0)==hidden,"each date counts only its hidden occurrences");JButton more=month.moreButtons.get(i);if(more!=null){check(more.isVisible()==(hidden>0),"overflow button follows actual visibility");if(more.isVisible())check(more.getText().equals("+ "+hidden+"개 일정"),"overflow label includes 일정 and accurate count");}
        }
        List<Component> visible=java.util.Arrays.stream(month.getComponents()).filter(Component::isVisible).toList();
        for(Component c:visible)check(c.getX()>=0&&c.getY()>=0&&c.getX()+c.getWidth()<=month.getWidth()&&c.getY()+c.getHeight()<=month.getHeight(),"visible monthly controls remain in resized bounds");
        for(int i=0;i<visible.size();i++)for(int j=i+1;j<visible.size();j++)check(!visible.get(i).getBounds().intersects(visible.get(j).getBounds()),"connected bars, date hit targets, and overflow labels do not overlap");
    }
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    static void render(JComponent c,Path path)throws Exception{BufferedImage im=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=im.createGraphics();c.printAll(g);g.dispose();ImageIO.write(im,"png",path.toFile());}
}
