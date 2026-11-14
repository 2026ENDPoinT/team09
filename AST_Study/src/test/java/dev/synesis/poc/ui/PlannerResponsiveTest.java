package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.font.TextLayout;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Real viewport resizing, complete 24-hour geometry, popup labels and focus-paint regressions. */
public final class PlannerResponsiveTest {
    private static int checks;
    private static final Path OUTPUT=Path.of("build/planner-responsive-20261018");
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planner-responsive-");System.setProperty("synesis.dataRoot",root.toString());Files.createDirectories(OUTPUT);
        PlannerStore store=new PlannerStore();Clock clock=Clock.fixed(Instant.parse("2026-10-18T03:00:00Z"),ZoneId.of("Asia/Seoul"));
        store.saveEvent(new Event("early","새벽 공부","",LocalDateTime.of(2026,10,12,0,0),LocalDateTime.of(2026,10,12,1,0),false,EventColor.BLUE,List.of(),false,Repeat.NONE,-1));
        store.saveEvent(new Event("late","하루 마무리","",LocalDateTime.of(2026,10,18,23,30),LocalDateTime.of(2026,10,19,0,0),false,EventColor.NAVY,List.of(),true,Repeat.NONE,-1));
        for(int i=0;i<2;i++)store.saveEvent(new Event("all-day-"+i,"종일 일정 "+(i+1),"",LocalDateTime.of(2026,10,13,0,0),LocalDateTime.of(2026,10,14,0,0),true,EventColor.TEAL,List.of(),false,Repeat.NONE,-1));
        for(int i=0;i<4;i++)store.saveTask(new Task("task-"+i,"복습할 내용 "+(i+1),LocalDate.now(clock),"개념을 정리해요.",false));
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDesign planner=new PlannerDesign(store,clock);JScrollPane host=new JScrollPane(planner);host.setBorder(null);
            for(int[] size:new int[][]{{1430,844},{1120,720},{900,650},{760,600},{640,650},{520,600},{360,540},{1800,1000}}){
                host.setSize(size[0],size[1]);layout(host);layout(host);JViewport viewport=host.getViewport();
                check(planner.getWidth()==viewport.getExtentSize().width&&planner.getHeight()==viewport.getExtentSize().height,"planner follows the actual viewport "+Arrays.toString(size));
                check(!host.getHorizontalScrollBar().isVisible()&&!host.getVerticalScrollBar().isVisible(),"no outer scrolling needed "+Arrays.toString(size));
                for(Component c:List.of(planner.add,planner.previous,planner.next,planner.today,planner.week,planner.month,planner.bell,planner.range,planner.calendar,planner.tasks,planner.upcoming,planner.goalButton))
                    check(c.getX()>=0&&c.getY()>=0&&c.getWidth()>0&&c.getHeight()>0&&c.getX()+c.getWidth()<=planner.getWidth()&&c.getY()+c.getHeight()<=planner.getHeight(),"control remains on screen: "+c.getName()+" "+Arrays.toString(size));
                check(planner.goalButton.getY()+planner.goalButton.getHeight()==planner.getHeight()-(planner.getWidth()<720?16:24),"goal pinned to window bottom");
                check(!planner.calendar.getBounds().intersects(planner.tasks.getBounds())&&!planner.calendar.getBounds().intersects(planner.upcoming.getBounds()),"supporting cards do not cover calendar");
                PlannerCalendar.WeekBody body=find(planner.calendar,PlannerCalendar.WeekBody.class);PlannerCalendar.WeekHeader header=find(planner.calendar,PlannerCalendar.WeekHeader.class);
                PlannerCalendar.Week week=find(planner.calendar,PlannerCalendar.Week.class);JViewport hours=week.timeline.getViewport();
                check(body!=null&&week.timeline.getVerticalScrollBar().isVisible()&&!week.timeline.getHorizontalScrollBar().isVisible(),"only the weekly timeline scrolls vertically");
                check(body.getHeight()>hours.getHeight()&&header.getWidth()==body.getWidth(),"fixed weekday header aligns with all seven scrollable columns");
                check(Math.abs(hours.getViewPosition().y-(body.minuteY(540)-body.gridTop()))<=1,"default timeline begins at 09:00 "+Arrays.toString(size)+" actual="+hours.getViewPosition().y+" expected="+(body.minuteY(540)-body.gridTop())+" minute="+planner.weeklyScrollMinute);
                check(body.minuteY(1080)-hours.getViewPosition().y<=hours.getHeight(),"18:00 also fits in the default viewport "+Arrays.toString(size));
                long days=Arrays.stream(header.getComponents()).filter(c->Boolean.TRUE.equals(((JComponent)c).getClientProperty("heading"))).count();check(days==7,"all seven weekday headings remain visible");
                for(Component c:header.getComponents())check(c.getX()>=0&&c.getX()+c.getWidth()<=header.getWidth()&&c.getY()+c.getHeight()<=header.getHeight(),"weekday and all-day controls are not clipped");
                for(JButton b:body.positions.keySet())check(b.getY()>=0&&b.getY()+b.getHeight()<=body.getHeight(),"midnight event remains within calendar");
                LocalDateTime at=body.timeAt(new Point(body.getWidth()-3,body.minuteY(1439)));check(at.toLocalDate().equals(LocalDate.of(2026,10,18))&&at.getHour()==23,"click mapping follows scaled Sunday grid");
                render(host,"week-"+size[0]+"x"+size[1]);testWeeklyScrolling(host,week,body,header,size[0]==1430);planner.setMonthly(true);layout(host);layout(host);
                PlannerCalendar.Month month=find(planner.calendar,PlannerCalendar.Month.class);check(month!=null,"monthly view remains reachable");
                for(Component c:month.getComponents())if(c.isVisible())check(c.getX()>=0&&c.getY()>=0&&c.getX()+c.getWidth()<=month.getWidth()&&c.getY()+c.getHeight()<=month.getHeight(),"monthly cell stays inside resized calendar");
                render(host,"month-"+size[0]+"x"+size[1]);planner.setMonthly(false);
            }
            testWeeklyResize(host,planner);
            // Neutral adjacent-month shading, independently of the app's navy palette.
            planner.setMonthly(true);host.setSize(1100,800);layout(host);layout(host);PlannerCalendar.Month month=find(planner.calendar,PlannerCalendar.Month.class);
            BufferedImage monthImage=paint(month);Color outside=new Color(monthImage.getRGB(2,month.headingHeight()+month.dateHeight()+3));check(outside.getRed()==outside.getGreen()&&outside.getGreen()==outside.getBlue(),"adjacent month background is neutral grey");
            testHeading();testDatePicker(planner,store,clock);testFocus(planner);testCorners();
        }catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("PASS: "+checks+" planner responsive, midnight, footer, typography, date-picker and focus checks; renders in "+OUTPUT.toAbsolutePath());
    }
    private static void testWeeklyScrolling(JScrollPane host,PlannerCalendar.Week week,PlannerCalendar.WeekBody body,PlannerCalendar.WeekHeader header,boolean images)throws Exception {
        JViewport hours=week.timeline.getViewport();Rectangle fixed=header.getBounds();int initial=hours.getViewPosition().y;
        week.timeline.dispatchEvent(new java.awt.event.MouseWheelEvent(week.timeline,java.awt.event.MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,80,100,0,false,java.awt.event.MouseWheelEvent.WHEEL_UNIT_SCROLL,3,1));
        check(hours.getViewPosition().y>initial,"mouse wheel scrolls the time grid");
        week.timeline.getVerticalScrollBar().setValue(0);layout(host);
        check(hours.getViewPosition().y==0&&body.minuteY(0)>=0&&body.minuteY(0)<hours.getHeight(),"scrolling to the top reveals 00:00");
        if(images)render(host,"week-scroll-00");
        week.timeline.getVerticalScrollBar().setValue(week.timeline.getVerticalScrollBar().getMaximum());layout(host);
        int end=body.minuteY(1440)-hours.getViewPosition().y;
        check(end>0&&end<hours.getHeight(),"scrolling to the bottom reveals 24:00");
        check(header.getBounds().equals(fixed)&&week.timeline.getColumnHeader().getViewPosition().y==0,"weekday and all-day header never scrolls vertically");
        LocalDateTime clicked=body.timeAt(new Point(body.getWidth()-3,hours.getViewPosition().y+hours.getHeight()-12));
        check(clicked.getHour()==23&&clicked.getDayOfWeek()==DayOfWeek.SUNDAY,"late Sunday hit testing uses scrolled body coordinates");
        if(images)render(host,"week-scroll-24");
        hours.setViewPosition(new Point(0,body.minuteY(540)-body.gridTop()));layout(host);
    }
    private static void testWeeklyResize(JScrollPane host,PlannerDesign planner){
        layout(host);layout(host);PlannerCalendar.Week week=find(planner.calendar,PlannerCalendar.Week.class);
        week.timeline.getViewport().setViewPosition(new Point(0,week.body.minuteY(360)-week.body.gridTop()));
        host.setSize(900,650);layout(host);layout(host);week=find(planner.calendar,PlannerCalendar.Week.class);
        check(Math.abs(week.timeline.getViewport().getViewPosition().y-(week.body.minuteY(360)-week.body.gridTop()))<=1,"resizing preserves the scrolled time instead of resetting it");
        planner.refresh();layout(host);layout(host);week=find(planner.calendar,PlannerCalendar.Week.class);
        check(Math.abs(week.timeline.getViewport().getViewPosition().y-(week.body.minuteY(360)-week.body.gridTop()))<=1,"refreshing events preserves the scrolled time");
    }
    private static void testHeading(){
        BufferedImage actual=new BufferedImage(220,56,BufferedImage.TYPE_INT_ARGB),expected=new BufferedImage(220,56,BufferedImage.TYPE_INT_ARGB);Font font=PlannerStyle.bold(28);
        Graphics2D a=PlannerStyle.quality(actual.createGraphics()),b=PlannerStyle.quality(expected.createGraphics());PlannerDialogs.drawText(a,"플래너",font,Color.BLACK,4,4,200);
        TextLayout text=new TextLayout("플래너",font,b.getFontRenderContext());b.setColor(Color.BLACK);text.draw(b,4,4+(40-text.getAscent()-text.getDescent())/2+text.getAscent());a.dispose();b.dispose();
        check(Arrays.equals(pixels(actual),pixels(expected)),"planner heading preserves every glyph pixel, including its bottom");
    }
    private static void testDatePicker(PlannerDesign planner,PlannerStore store,Clock clock)throws Exception {
        PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,planner.state,null,LocalDateTime.of(2026,10,18,10,0),planner::accept,clock);
        JPopupMenu popup=editor.startDate.popup();popup.setSize(popup.getPreferredSize());layout(popup);List<JButton> numbers=new ArrayList<>();collectNumbers(popup,numbers);check(numbers.size()==42,"date picker includes complete six-week grid");
        for(JButton b:numbers){Insets insets=b.getInsets();int available=b.getWidth()-insets.left-insets.right;check(b.getFontMetrics(b.getFont()).stringWidth(b.getText())<=available,"date number is never replaced with ellipsis: "+b.getText());}
        render(popup,"date-picker");numbers.stream().filter(b->b.getText().equals("31")).findFirst().orElseThrow().doClick();check(editor.startDate.date().equals(LocalDate.of(2026,10,31)),"two-digit day selection still works");
        for(int width:new int[]{920,768,600,920}){
            editor.setSize(width,620);layout(editor);layout(editor);PlannerDialogs.EditorBody body=find(editor,PlannerDialogs.EditorBody.class);
            check(body!=null&&body.getWidth()==body.getParent().getWidth(),"event editor follows its viewport width");
            check(body.preview.getX()>=0&&body.preview.getX()+body.preview.getWidth()<=body.getWidth(),"event preview is reachable without horizontal clipping");
            for(Component c:body.form.getComponents())check(c.getX()>=0&&c.getX()+c.getWidth()<=body.form.getWidth(),"event input stays inside compact form");
            render(editor,"event-editor-"+width);
        }
    }
    private static void testFocus(PlannerDesign planner){
        KeyboardFocusManager previous=KeyboardFocusManager.getCurrentKeyboardFocusManager();class Focus extends DefaultKeyboardFocusManager{Component owner;@Override public Component getFocusOwner(){return owner;}}
        Focus focus=new Focus();KeyboardFocusManager.setCurrentKeyboardFocusManager(focus);
        try{
            PlannerCalendar calendar=(PlannerCalendar)planner.calendar.getComponent(0);JButton date=calendar.dateButton(LocalDate.of(2026,10,25));date.setSize(100,32);
            for(JButton button:List.of(date,planner.add,planner.week,planner.goalButton,PlannerStyle.button("태그 관리",false,()->{}))){if(button.getWidth()==0)button.setSize(160,40);focus.owner=null;int[] before=pixels(paint(button));focus.owner=button;check(button.hasFocus(),"focus test exercises actual focus state");check(Arrays.equals(before,pixels(paint(button))),"focus adds no click outline: "+button.getText());}
        }finally{KeyboardFocusManager.setCurrentKeyboardFocusManager(previous);}
    }
    private static void testCorners(){PlannerStyle.Card card=new PlannerStyle.Card(Color.WHITE,12);card.setLayout(new BorderLayout());JPanel child=new JPanel();child.setBackground(Color.WHITE);card.add(child);card.setSize(240,160);layout(card);BufferedImage image=paint(card);check((image.getRGB(0,80)&0xffffff)==(PlannerStyle.BORDER.getRGB()&0xffffff)&&((image.getRGB(120,0)&0xffffff)==(PlannerStyle.BORDER.getRGB()&0xffffff)),"children cannot erase calendar outline");}
    private static void collectNumbers(Container parent,List<JButton> result){for(Component c:parent.getComponents()){if(c instanceof JButton b&&b.getText()!=null&&b.getText().matches("\\d{1,2}"))result.add(b);if(c instanceof Container nested)collectNumbers(nested,result);}}
    private static <T extends Component>T find(Container root,Class<T> type){for(Component c:root.getComponents()){if(type.isInstance(c))return type.cast(c);if(c instanceof Container child){T result=find(child,type);if(result!=null)return result;}}return null;}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static BufferedImage paint(JComponent c){BufferedImage image=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();c.printAll(g);g.dispose();return image;}
    private static int[] pixels(BufferedImage image){return image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth());}
    private static void render(JComponent c,String name)throws Exception{ImageIO.write(paint(c),"png",OUTPUT.resolve(name+".png").toFile());}
}
