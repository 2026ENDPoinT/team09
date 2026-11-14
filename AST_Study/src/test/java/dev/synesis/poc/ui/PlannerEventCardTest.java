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

/** Preview/actual pixel parity and restored offscreen-event controls, using disposable data only. */
public final class PlannerEventCardTest {
    static int checks;
    static final Path OUT=Path.of("tmp/calendar-figma-20261019/event-card");
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);PlannerStore store=new PlannerStore(Files.createTempDirectory("planner-event-card-").resolve("planner.json"));
        LocalDate day=LocalDate.of(2026,10,22);store.saveTags(List.of(),List.of(new Tag("exam","중간고사")));
        Event sample=new Event("sample","현예이시험","중간고사",day.atTime(15,0),day.atTime(17,0),false,EventColor.ROSE,List.of("exam"),true,Repeat.NONE,-1);store.saveEvent(sample);
        Event normal=new Event("normal",sample.title(),sample.description(),sample.start(),sample.end(),false,sample.color(),sample.tagIds(),false,Repeat.NONE,-1);
        store.saveEvent(new Event("early","이른 수업","",day.atTime(3,0),day.atTime(4,0),false,EventColor.TEAL,List.of(),false,Repeat.NONE,-1));
        store.saveEvent(new Event("late","늦은 복습","",day.atTime(23,0),day.atTime(23,50),false,EventColor.BLUE,List.of(),false,Repeat.NONE,-1));
        Clock clock=Clock.fixed(Instant.parse("2026-10-22T02:00:00Z"),ZoneId.of("Asia/Seoul"));
        SwingUtilities.invokeAndWait(()->{try{
            State state=store.load();PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,state,sample,sample.start(),s->{},clock);editor.preview.setSize(280,550);
            BufferedImage preview=paint(editor.preview,280,550,PlannerStyle.SURFACE);
            JButton actual=PlannerWeekCalendarSkin.eventButton(new Occurrence(sample,sample.start(),sample.end()),false,state,()->{});
            BufferedImage large=paint(actual,248,132,PlannerStyle.SURFACE);check(Arrays.equals(pixels(large),pixels(preview.getSubimage(16,82,248,132))),"preview and actual card use identical pixels at the same size");
            save(preview,"preview.png");save(large,"actual-large.png");BufferedImage compact=paint(actual,134,52,Color.WHITE);save(compact,"actual-compact.png");
            check(new Color(compact.getRGB(100,10)).equals(PlannerEventCard.background(new Color(EventColor.ROSE.rgb))),"calendar card uses a pastel background");
            check(new Color(compact.getRGB(2,20)).equals(PlannerEventCard.accent(new Color(EventColor.ROSE.rgb))),"left stripe uses the more saturated color from the same family");
            check(new Color(compact.getRGB(20,35)).equals(PlannerEventCard.chipFill(PlannerEventCard.background(new Color(EventColor.ROSE.rgb)))),"tag chip is visible on a two-hour event");
            JButton plain=PlannerWeekCalendarSkin.eventButton(new Occurrence(normal,normal.start(),normal.end()),false,state,()->{});
            check(Arrays.equals(pixels(compact),pixels(paint(plain,134,52,Color.WHITE))),"important flag never changes card colors or fills");
            PlannerDesign planner=new PlannerDesign(store,clock);planner.setSize(1430,844);layout(planner);
            PlannerCalendar calendar=(PlannerCalendar)planner.calendar.getComponent(0);PlannerCalendar.Week week=(PlannerCalendar.Week)calendar.getComponent(0);
            check(week.hidden(3,true).size()==1&&week.hidden(3,false).size()==1,"offscreen events counted above and below the correct day");
            check(week.edgeBadges.stream().filter(Component::isVisible).count()==2,"only relevant hidden-event bubbles are shown");
            check(((PlannerCalendar.WeekHeader)week.timeline.getColumnHeader().getView()).getComponentCount()==7,"restoring edge bubbles does not restore task badges or header agenda");
            save(paint(calendar,calendar.getWidth(),calendar.getHeight(),Color.WHITE),"calendar-with-bubbles.png");
            JButton below=week.edgeBadges.stream().filter(b->b.isVisible()&&Boolean.FALSE.equals(b.getClientProperty("planner.edgeAbove"))).findFirst().orElseThrow();below.doClick();check(week.hidden(3,false).isEmpty(),"clicking lower bubble reveals the hidden event");
            week.timeline.getViewport().setViewPosition(new Point(0,0));check(week.edgeBadges.stream().noneMatch(b->b.isVisible()&&Boolean.TRUE.equals(b.getClientProperty("planner.edgeAbove"))),"upper bubbles disappear at start of day");
            week.timeline.getViewport().setViewPosition(new Point(0,week.body.getHeight()-week.timeline.getViewport().getHeight()));check(week.edgeBadges.stream().noneMatch(b->b.isVisible()&&Boolean.FALSE.equals(b.getClientProperty("planner.edgeAbove"))),"lower bubbles disappear at end of day");
            check(store.load().events().size()==3,"viewing cards and clicking bubbles do not modify stored events");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" event preview parity, compact styling and hidden-event bubble checks");
    }
    static BufferedImage paint(JComponent c,int w,int h,Color background){c.setSize(w,h);BufferedImage image=new BufferedImage(w,h,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(background);g.fillRect(0,0,w,h);c.printAll(g);g.dispose();return image;}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static int[] pixels(BufferedImage image){return image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth());}
    static void save(BufferedImage image,String name)throws Exception{ImageIO.write(image,"png",OUT.resolve(name).toFile());}
}
